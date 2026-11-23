import sqlite3
import time

import pytest

import common
from common import _contains, is_private, private_visible, safe_title


@pytest.mark.parametrize("app,title", [
    ("msedge.exe", "Bank - [InPrivate] - Microsoft​ Edge"),
    ("firefox.exe", "Mozilla Firefox Private Browsing"),
    ("chrome.exe", "Inbox (3) - me@gmail.com - Gmail - Google Chrome"),
    ("1Password.exe", "1Password"),
    ("Bitwarden.exe", "Bitwarden"),
    ("chrome.exe", "Vaults | Bitwarden Web vault - Google Chrome"),
    ("Code.exe", ".env - watcher - Visual Studio Code"),
    ("Code.exe", ".env.local - web - Visual Studio Code"),
    ("Code.exe", "id_rsa - .ssh - Visual Studio Code"),
    ("Code.exe", "credentials.json - app - Visual Studio Code"),
    ("chrome.exe", "Chase Online - Account Summary - Google Chrome"),
    ("chrome.exe", "Capital One | Credit Cards - Google Chrome"),
    ("chrome.exe", "Robinhood - Google Chrome"),
    ("chrome.exe", "Chats • Instagram - Google Chrome"),
    ("chrome.exe", "Instagram • Direct - Google Chrome"),
    ("WhatsApp.exe", "WhatsApp"),
    ("Telegram.exe", "Telegram"),
    ("Discord.exe", "@rishi - Discord"),
    ("chrome.exe", "Messenger | Facebook - Google Chrome"),
    ("OUTLOOK.EXE", "Inbox - Outlook"),
    ("LockApp.exe", ""),
    ("chrome.exe", "Your Google Authenticator codes - Google Chrome"),
    ("chrome.exe", "MyChart - Test Results - Google Chrome"),
])
def test_private_titles_are_caught(app, title):
    assert is_private(app, title)
    assert safe_title(app, title) == "(private)"


@pytest.mark.parametrize("app,title", [
    ("WindowsTerminal.exe", "claude - watcher"),
    ("Code.exe", "watcher.py - watcher - Visual Studio Code"),
    ("chrome.exe", "Hacker News - Google Chrome"),
    ("chrome.exe", "Messaging | LinkedIn - Google Chrome"),  # outreach is work he wants coached
    ("League of Legends.exe", "Teamfight Tactics"),
    ("cs2.exe", "Counter-Strike 2"),
    ("Discord.exe", "#general | Wingmate - Discord"),
])
def test_normal_titles_pass(app, title):
    assert not is_private(app, title)
    assert safe_title(app, title) == title


def test_private_visible_detects_side_by_side_window():
    mon = (0, 0, 1920, 1080)
    wins = [(1, "Code.exe", "watcher.py - VS Code", (0, 0, 960, 1080)),
            (2, "chrome.exe", "Chase - Google Chrome", (960, 0, 1920, 1080))]
    assert private_visible(wins, mon) == "Chase - Google Chrome"


def test_private_window_fully_covered_is_ignored():
    mon = (0, 0, 1920, 1080)
    wins = [(1, "Code.exe", "watcher.py", (0, 0, 1920, 1080)),
            (2, "OUTLOOK.EXE", "Inbox - Outlook", (100, 100, 900, 700))]
    assert private_visible(wins, mon) is None


def test_private_window_on_other_monitor_is_ignored():
    wins = [(2, "OUTLOOK.EXE", "Inbox - Outlook", (1920, 0, 3840, 1080))]
    assert private_visible(wins, (0, 0, 1920, 1080)) is None
    assert private_visible(wins, (1920, 0, 3840, 1080)) == "Inbox - Outlook"


def test_private_visible_uses_custom_check_for_incognito():
    wins = [(7, "chrome.exe", "Hacker News - Google Chrome", (0, 0, 800, 600))]
    assert private_visible(wins, (0, 0, 1920, 1080), lambda a, t, h: h == 7)


def test_contains():
    assert _contains((0, 0, 10, 10), (1, 1, 9, 9))
    assert not _contains((0, 0, 10, 10), (1, 1, 11, 9))


def test_is_incognito_only_probes_chromium(monkeypatch):
    called = []
    monkeypatch.setattr(common.subprocess, "run", lambda *a, **k: called.append(1))
    assert common.is_incognito(123, "msedge.exe") is False
    assert common.is_incognito(None, "chrome.exe") is False
    assert not called


def test_is_incognito_parses_and_caches(monkeypatch):
    class R:
        stdout = "\nTESTPAGE - Google Chrome (Incognito)\n"
    calls = []
    monkeypatch.setattr(common.subprocess, "run", lambda *a, **k: calls.append(1) or R())
    common._incog_cache.clear()
    assert common.is_incognito(4242, "chrome.exe") is True
    assert common.is_incognito(4242, "chrome.exe") is True
    assert len(calls) == 1


def test_is_incognito_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(common.subprocess, "run", boom)
    common._incog_cache.clear()
    assert common.is_incognito(99, "chrome.exe") is True
    assert 99 not in common._incog_cache  # retried next time


# ---------- migrations ----------
OLD_SCHEMA = """
CREATE TABLE activity (ts REAL, app TEXT, title TEXT, idle INTEGER);
CREATE INDEX activity_ts ON activity(ts);
CREATE TABLE shots (id INTEGER PRIMARY KEY, ts REAL, path TEXT, app TEXT, title TEXT, analyzed INTEGER DEFAULT 0);
CREATE TABLE observations (id INTEGER PRIMARY KEY, ts_start REAL, ts_end REAL, category TEXT, focus INTEGER,
  summary TEXT, tips_json TEXT, input_tokens INTEGER, output_tokens INTEGER);
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
INSERT INTO activity VALUES (1, 'a.exe', 't', 0);
INSERT INTO meta VALUES ('paused', '0');
"""


def test_migrates_pre_versioning_db_without_losing_data(tmp_path):
    p = tmp_path / "old.db"
    raw = sqlite3.connect(p)
    raw.executescript(OLD_SCHEMA)
    raw.close()
    c = common.db(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == common.SCHEMA_VERSION
    assert c.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 1
    assert common.meta_get(c, "paused") == "0"
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert {"activity_daily", "shots_analyzed", "observations_ts_end"} <= names
    c.close()
    c2 = common.db(p)  # idempotent reopen
    assert c2.execute("PRAGMA user_version").fetchone()[0] == common.SCHEMA_VERSION


def test_fresh_db_uses_wal(tmp_path):
    c = common.db(tmp_path / "w.db")
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_rollup_and_prune(con):
    now_ = time.time()
    today0 = common.day_start(now_)
    old = today0 - 40 * 86400 + 3600
    yday = today0 - 86400 + 3600
    con.executemany("INSERT INTO activity VALUES(?,?,?,?)",
                    [(old, "a.exe", "x", 0)] * 10 + [(yday, "b.exe", "y", 0)] * 5 + [(yday, "b.exe", "y", 1)] * 5
                    + [(now_, "c.exe", "z", 0)] * 3)
    deleted = common.rollup_and_prune(con, keep_days=30, now_ts=now_)
    assert deleted == 10
    daily = {r["app"]: r["seconds"] for r in con.execute("SELECT * FROM activity_daily")}
    assert daily == {"a.exe": 10 * common.SAMPLE_SECONDS, "b.exe": 5 * common.SAMPLE_SECONDS}
    common.rollup_and_prune(con, keep_days=30, now_ts=now_)  # running again doesn't double count
    assert con.execute("SELECT SUM(seconds) FROM activity_daily").fetchone()[0] == 15 * common.SAMPLE_SECONDS
    assert con.execute("SELECT COUNT(*) FROM activity WHERE app='c.exe'").fetchone()[0] == 3


def test_fmt_dur():
    assert common.fmt_dur(59) == "0m"
    assert common.fmt_dur(3600 + 5 * 60) == "1h 05m"


def test_redact_secrets():
    r = common.redact_secrets
    assert "eddiekart" not in r("Set REQUIRE_LOGIN=1 with a random password, rotate 'eddiekart' (it's in scrollback).")
    assert r("set DASHBOARD_PASSWORD=hunter22 now") == "set DASHBOARD_PASSWORD=[redacted] now"
    assert "hunter22" not in r("the password is hunter22")
    assert "sk-ant" not in r("key sk-ant-api03-abcdefghijklmnop leaked")
    assert "u:p@" not in r("DATABASE_URL=postgresql://u:p@host/db")
    for keep in ["the password is empty", "the password field was empty", "Claude stalled on 'Authentication failed'.",
                 "He opened 'watcher' in Chrome."]:
        assert r(keep) == keep
