"""Shared config, DB, and Win32 helpers for the screen watcher."""
import ctypes
import ctypes.wintypes as wt
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # never overrides vars already set (tests rely on that)

# WATCHER_DATA_DIR lets tests / a second instance use a separate DB + shots folder.
DATA = Path(os.getenv("WATCHER_DATA_DIR") or (ROOT / "data")).resolve()
SHOTS = DATA / "shots"
REPORTS = Path(os.getenv("WATCHER_REPORTS_DIR") or (ROOT / "reports")).resolve()
DB_PATH = DATA / "watcher.db"
for d in (DATA, SHOTS, REPORTS):
    d.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("WATCHER_MODEL", "claude-haiku-5-5")
SAMPLE_SECONDS = int(os.getenv("SAMPLE_SECONDS", "3"))        # window/idle sampling
SHOT_SECONDS = int(os.getenv("SHOT_SECONDS", "60"))           # screenshot cadence
ANALYZE_SECONDS = int(os.getenv("ANALYZE_SECONDS", "600"))    # vision analysis cadence
IDLE_SECONDS = int(os.getenv("IDLE_SECONDS", "120"))          # no input for this long = away
MAX_SHOTS_PER_ANALYSIS = int(os.getenv("MAX_SHOTS_PER_ANALYSIS", "6"))
KEEP_SCREENSHOTS = os.getenv("KEEP_SCREENSHOTS", "0") == "1"
NOTIFY = os.getenv("WATCHER_NOTIFY", "0") == "1"                # desktop toasts off unless opted in
NOTIFY_COOLDOWN = int(os.getenv("NOTIFY_COOLDOWN", "2700"))   # min seconds between toasts
SHOT_MAX_AGE = int(os.getenv("SHOT_MAX_AGE", "3600"))         # unanalyzed shots older than this are deleted
RAW_RETENTION_DAYS = int(os.getenv("RAW_RETENTION_DAYS", "30"))  # raw 3s activity rows kept this long
DASH_PORT = int(os.getenv("WATCHER_DASH_PORT", "8765"))

# Never screenshot (or send titles of) windows whose title or process matches this.
DEFAULT_PRIVATE = (
    # password managers / secrets
    r"password|passwort|1password|bitwarden|lastpass|keepass|dashlane|keeper|nordpass|proton ?pass|authenticator|"
    r"\b2fa\b|\botp\b|recovery (codes?|phrase)|seed phrase|private key|\.env\b|\.env\.|\.pem\b|id_rsa|id_ed25519|"
    r"credentials?\.json|secrets?\.(json|ya?ml|toml)|\.npmrc|\.pgpass|"
    # private browsing
    r"incognito|inprivate|private browsing|private window|"
    # money / identity
    r"bank|chase|wells fargo|citi(bank|cards)?\b|capital ?one|american express|\bamex\b|discover card|schwab|fidelity|"
    r"vanguard|robinhood|coinbase|paypal|venmo|cash ?app|zelle|stripe\.com/.*payments|turbotax|\birs\b|"
    r"social security|\bssn\b|medical|patient portal|mychart|"
    # personal mail and DMs
    r"gmail|outlook|inbox|proton ?mail|magic link|whatsapp|telegram|signal|messenger|imessage|"
    r"instagram.*(chats?|direct|messages)|(chats?|direct|messages)\W{1,5}instagram|direct messages?|^@[^\s]+ - discord|"
    # lock screen / secure desktop
    r"lockapp|logonui|consent\.exe"
)
PRIVATE_RE = re.compile(os.getenv("PRIVATE_PATTERN", DEFAULT_PRIVATE), re.I)
REDACTED = "(private)"


def is_private(app: str, title: str) -> bool:
    return bool(PRIVATE_RE.search(f"{app or ''} {title or ''}")) or bool(PRIVATE_RE.search(title or ""))


# Things a vision model might copy off the screen that must never be stored or synced.
_KEYWORD = r"(?:password|passwd|passphrase|secret|token|api[_ -]?key|credential)s?"
# well-known key formats, anywhere
_KEY_FORMATS = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})|postgres(?:ql)?://\S+")
# PASSWORD=hunter2, api_key: abc123
_ASSIGN = re.compile(r"(?i)(\w*" + _KEYWORD + r"\w*\s*[=:]\s*)[\"'`]?[^\s\"'`,;)]+")
# "password is hunter2" (but not "password is empty")
_IS = re.compile(r"(?i)(\b" + _KEYWORD + r"\s+(?:is|was|to|of)\s+)(?!(?:empty|set|wrong|correct|required|missing|"
                 r"visible|exposed|still|now|in|on|the|a|an|not|being|shown|weak|strong|public)\b)[\"'`]?[^\s\"'`,;.)]{3,}")
# any quoted single word in a sentence that talks about passwords/secrets: "rotate 'eddiekart'"
_QUOTED = re.compile(r"[\"'`‘’“”][^\s\"'`‘’“”]{3,40}[\"'`‘’“”]")
_SECRET_TALK = re.compile(r"(?i)\b" + _KEYWORD + r"\b|\brotate\b")


def redact_secrets(text: str) -> str:
    """Strip secrets a vision model copied off the screen (it's told not to; this is the backstop)."""
    text = _KEY_FORMATS.sub("[redacted]", text or "")
    text = _ASSIGN.sub(lambda m: m.group(1) + "[redacted]", text)
    text = _IS.sub(lambda m: m.group(1) + "[redacted]", text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(_QUOTED.sub("[redacted]", p) if _SECRET_TALK.search(p) else p for p in parts)


def safe_title(app: str, title: str) -> str:
    """Window title with private windows redacted. Use before sending a title anywhere."""
    return REDACTED if is_private(app, title) else (title or "")


PROFILE_PATH = ROOT / "profile.md"


def profile() -> str:
    return PROFILE_PATH.read_text(encoding="utf-8") if PROFILE_PATH.exists() else ""


# ---------- DB ----------
# Each entry upgrades the schema by one version (PRAGMA user_version). Append only.
MIGRATIONS = [
    # 1: original schema
    """
    CREATE TABLE IF NOT EXISTS activity (ts REAL, app TEXT, title TEXT, idle INTEGER);
    CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
    CREATE TABLE IF NOT EXISTS shots (
      id INTEGER PRIMARY KEY, ts REAL, path TEXT, app TEXT, title TEXT, analyzed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY, ts_start REAL, ts_end REAL, category TEXT, focus INTEGER,
      summary TEXT, tips_json TEXT, input_tokens INTEGER, output_tokens INTEGER);
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    """,
    # 2: indexes for the dashboard / analysis queries
    """
    CREATE INDEX IF NOT EXISTS shots_analyzed ON shots(analyzed, ts);
    CREATE INDEX IF NOT EXISTS observations_ts_end ON observations(ts_end);
    """,
    # 3: daily rollup so raw 3s rows can be pruned without losing weekly trends
    """
    CREATE TABLE IF NOT EXISTS activity_daily (day TEXT, app TEXT, seconds INTEGER, PRIMARY KEY (day, app));
    """,
]
SCHEMA_VERSION = len(MIGRATIONS)


def migrate(con: sqlite3.Connection) -> int:
    v = con.execute("PRAGMA user_version").fetchone()[0]
    while v < SCHEMA_VERSION:
        con.executescript(f"BEGIN; {MIGRATIONS[v]} PRAGMA user_version={v + 1}; COMMIT;")
        v += 1
    return v


def db(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")  # readers (dashboard) don't block the 3s writer
        con.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    migrate(con)
    return con


def meta_get(con, k, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def meta_set(con, k, v, commit=True):
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))
    if commit:
        con.commit()


def day_start(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def rollup_and_prune(con, keep_days: int = RAW_RETENTION_DAYS, now_ts: float | None = None) -> int:
    """Roll raw activity older than today into activity_daily, then delete raw rows older than keep_days.
    Returns rows deleted."""
    now_ts = now_ts or time.time()
    today0 = day_start(now_ts)
    last = float(meta_get(con, "rolled_until", 0) or 0)
    if last < today0:
        con.execute(
            "INSERT INTO activity_daily(day, app, seconds) "
            "SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') d, COALESCE(app,'?'), COUNT(*)*? "
            "FROM activity WHERE ts>=? AND ts<? AND idle=0 GROUP BY d, COALESCE(app,'?') "
            "ON CONFLICT(day, app) DO UPDATE SET seconds = activity_daily.seconds + excluded.seconds",
            (SAMPLE_SECONDS, last, today0))
        meta_set(con, "rolled_until", today0, commit=False)
    cutoff = today0 - keep_days * 86400
    n = con.execute("DELETE FROM activity WHERE ts<?", (cutoff,)).rowcount
    con.commit()
    return n


# ---------- Win32 ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixel coords on hi-dpi
except Exception:
    pass


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def idle_seconds() -> float:
    lii = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    now_ = kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now_ - lii.dwTime) & 0xFFFFFFFF) / 1000.0


def window_title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def process_name(hwnd) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    app = ""
    if h:
        size = wt.DWORD(1024)
        pbuf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
            app = Path(pbuf.value).name
        kernel32.CloseHandle(h)
    return app


def foreground():
    """Return (hwnd, process_name, window_title)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, "", ""
    return hwnd, process_name(hwnd), window_title(hwnd)


def window_rect(hwnd):
    r = wt.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


def window_center(hwnd):
    r = window_rect(hwnd)
    return ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2) if r else None


def _cloaked(hwnd) -> bool:
    v = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v))  # DWMWA_CLOAKED
    except Exception:
        return False
    return v.value != 0


def visible_windows():
    """Top-level visible, non-minimized, non-cloaked windows, top of the z-order first:
    [(hwnd, app, title, (l, t, r, b))]."""
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h) and not user32.IsIconic(h) and not _cloaked(h):
            title = window_title(h)
            r = window_rect(h)
            if title and r and r[2] > r[0] and r[3] > r[1]:
                out.append((h, process_name(h), title, r))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _contains(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def private_visible(windows, area, is_priv=None) -> str | None:
    """Title of a private window that is at least partly visible inside `area` (monitor rect), else None.
    `windows` is z-ordered top first. A window fully covered by one window above it counts as hidden."""
    is_priv = is_priv or (lambda app, title, hwnd: is_private(app, title))
    above = []
    for h, app, title, r in windows:
        if _intersects(r, area) and is_priv(app, title, h):
            if not any(_contains(a, r) for a in above):
                return title
        above.append(r)
    return None


# Chrome/Brave don't put "Incognito" in the window title (verified 2026-11-11), but UI Automation
# exposes it on the BrowserRootView child: "<page> - Google Chrome (Incognito)". Cached per window.
CHROMIUM = {"chrome.exe", "brave.exe", "vivaldi.exe", "opera.exe", "arc.exe"}
_incog_cache: dict[int, bool] = {}


def is_incognito(hwnd, app: str) -> bool:
    if (app or "").lower() not in CHROMIUM or not hwnd:
        return False
    key = int(hwnd)
    if key in _incog_cache:
        return _incog_cache[key]
    ps = ("Add-Type -AssemblyName UIAutomationClient;"
          "$w=[System.Windows.Automation.TreeWalker]::RawViewWalker;"
          f"$e=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{key});"
          "$c=$w.GetFirstChild($e); while($c){ $c.Current.Name; $c=$w.GetNextSibling($c) }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, timeout=10, creationflags=0x08000000)
        res = bool(re.search(r"\((Incognito|Private)\)|Private window", r.stdout, re.I))
    except Exception:
        return True  # can't tell: treat as private (fail closed), retry next time
    if len(_incog_cache) > 500:
        _incog_cache.clear()
    _incog_cache[key] = res
    return res


def fmt_dur(sec: float) -> str:
    sec = int(sec)
    h, m = divmod(sec // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def now() -> float:
    return time.time()
