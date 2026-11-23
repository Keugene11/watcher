"""Derived metrics shared by the daily report and the local dashboard: deep-work blocks, weekly trends, tip groups.
Pure functions over the DB; no API calls."""
import json
import re
import time
from collections import Counter

from common import SAMPLE_SECONDS, day_start

DEEP = 7        # focus score that counts as deep work
LOW = 4         # focus score that counts as a time sink
NOT_WORK = {"gaming", "entertainment"}  # focused TFT is still not deep work toward his goals


def focus_blocks(obs, min_focus=DEEP, max_gap=120, exclude=NOT_WORK):
    """Merge consecutive observations with focus >= min_focus into blocks.
    obs: rows/dicts with ts_start, ts_end, focus, category (any order). Returns
    [{'start','end','seconds','avg_focus','category'}] longest first."""
    rows = sorted((o for o in obs if o["category"] not in exclude), key=lambda o: o["ts_start"])
    blocks, cur = [], None
    for o in rows:
        if o["focus"] >= min_focus and cur and o["ts_start"] - cur["end"] <= max_gap:
            cur["end"] = o["ts_end"]
            cur["f"].append(o["focus"])
            cur["cats"][o["category"]] += o["ts_end"] - o["ts_start"]
        elif o["focus"] >= min_focus:
            cur = {"start": o["ts_start"], "end": o["ts_end"], "f": [o["focus"]],
                   "cats": Counter({o["category"]: o["ts_end"] - o["ts_start"]})}
            blocks.append(cur)
        else:
            cur = None
    out = [{"start": b["start"], "end": b["end"], "seconds": b["end"] - b["start"],
            "avg_focus": round(sum(b["f"]) / len(b["f"]), 1), "category": b["cats"].most_common(1)[0][0]}
           for b in blocks]
    return sorted(out, key=lambda b: -b["seconds"])


def time_sinks(obs, max_focus=LOW):
    """Low-focus windows grouped by category: [(category, seconds, [summaries])] biggest first."""
    g = {}
    for o in obs:
        if o["focus"] <= max_focus:
            e = g.setdefault(o["category"], [0, []])
            e[0] += o["ts_end"] - o["ts_start"]
            e[1].append(o["summary"])
    return sorted(((c, s, sums) for c, (s, sums) in g.items()), key=lambda x: -x[1])


def active_by_day(con, t0, t1):
    """{day: active seconds} from the daily rollup plus raw rows not rolled up yet."""
    out = Counter()
    for r in con.execute("SELECT day, SUM(seconds) s FROM activity_daily WHERE day>=? AND day<? GROUP BY day",
                         (time.strftime("%Y-%m-%d", time.localtime(t0)), time.strftime("%Y-%m-%d", time.localtime(t1)))):
        out[r["day"]] += r["s"]
    rolled = {d for d in out}
    for r in con.execute("SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') d, COUNT(*) n FROM activity "
                         "WHERE ts>=? AND ts<? AND idle=0 GROUP BY d", (t0, t1)):
        if r["d"] not in rolled:
            out[r["d"]] += r["n"] * SAMPLE_SECONDS
    return out


def week_trend(con, now=None, days=7):
    """Last `days` days, oldest first: [{'day','active','focus','checks','deep','top'}]."""
    now = now or time.time()
    today0 = day_start(now)
    t0 = today0 - (days - 1) * 86400
    active = active_by_day(con, t0, today0 + 86400)
    obs_by_day = {}
    for o in con.execute("SELECT * FROM observations WHERE ts_end>=? ORDER BY ts_start", (t0,)):
        obs_by_day.setdefault(time.strftime("%Y-%m-%d", time.localtime(o["ts_end"])), []).append(o)
    out = []
    for i in range(days):
        d0 = t0 + i * 86400 + 3600  # +1h survives DST shifts
        day = time.strftime("%Y-%m-%d", time.localtime(d0))
        obs = obs_by_day.get(day, [])
        cats = Counter()
        for o in obs:
            cats[o["category"]] += o["ts_end"] - o["ts_start"]
        out.append({
            "day": day, "active": active.get(day, 0), "checks": len(obs),
            "focus": round(sum(o["focus"] for o in obs) / len(obs), 1) if obs else None,
            "deep": sum(b["seconds"] for b in focus_blocks(obs)),
            "top": cats.most_common(1)[0][0] if cats else None,
        })
    return out


def deep_work_streak(trend, min_seconds=3600):
    """Consecutive days (ending today, or yesterday if today has none yet) with >= min_seconds of deep work."""
    days = list(trend)
    if days and days[-1]["deep"] < min_seconds:
        days = days[:-1]  # today isn't over; don't break the streak for it
    n = 0
    for d in reversed(days):
        if d["deep"] < min_seconds:
            break
        n += 1
    return n


def grouped_tips(tips, dup):
    """Collapse near-duplicate tips: [(tip_dict, count, first_ts)] ordered by impact then count.
    tips: [(ts, tip_dict)]; dup(a, [b]) -> bool."""
    groups = []
    for ts, t in sorted(tips, key=lambda x: x[0]):
        for g in groups:
            if dup(t["tip"], [g[0]["tip"]]):
                g[1] += 1
                if ["high", "medium", "low"].index(t["impact"]) < ["high", "medium", "low"].index(g[0]["impact"]):
                    g[0] = {**t}
                break
        else:
            groups.append([dict(t), 1, ts])
    rank = {"high": 0, "medium": 1, "low": 2}
    return [tuple(g) for g in sorted(groups, key=lambda g: (rank[g[0]["impact"]], -g[1], g[2]))]


def day_observations(con, t0):
    return [dict(o) | {"tips": json.loads(o["tips_json"] or "[]")} for o in con.execute(
        "SELECT * FROM observations WHERE ts_end>=? AND ts_end<? ORDER BY ts_start", (t0, t0 + 86400))]


# ---------- day facts (computed here, synced to the cloud, fed to the daily feedback) ----------
DAY_START_HOUR = 5  # facts use a 5am-to-5am window so a 2am session belongs to the day it was part of
WORK = {"coding", "job_hunting", "learning", "admin", "communication"}
GAME_APPS = {"cs2.exe", "league of legends.exe", "leagueclientux.exe", "valorant.exe", "valorant-win64-shipping.exe",
             "dota2.exe", "r5apex.exe", "fortniteclient-win64-shipping.exe", "overwatch.exe", "rocketleague.exe"}
_VIDEO = re.compile(r"YouTube|Twitch|\bKick\b|Netflix|Prime Video|Hulu|Disney\+|Crunchyroll", re.I)
_SOCIAL = re.compile(r"(^|[\s|-])(Instagram|Reddit|TikTok)\b| / X\b|Feed \| LinkedIn|Home / X", re.I)


def kind(app, title):
    """'game' | 'video' | 'social' | None for one activity sample."""
    a = (app or "").lower()
    if a in GAME_APPS:
        return "game"
    if _VIDEO.search(title or ""):
        return "video"
    if _SOCIAL.search(title or ""):
        return "social"
    return None


def _pretty(site):
    s = (site or "?").removesuffix(".exe")
    return {"cs2": "CS2", "claude": "Claude", "Deck": "Deck", "Code": "VS Code", "WindowsTerminal": "Terminal",
            "steamwebhelper": "Steam", "League of Legends": "League/TFT", "(private)": "private windows",
            "private": "private windows"}.get(s, s)


def sleep_bounds(con, t0, t1, gap=3 * 3600):
    """(wake, bed): first activity after a 3h+ break that ends inside [t0, t1), and the start of the next 3h+ break.
    Either can be None (pulled an all-nighter / still going)."""
    ts = [r[0] for r in con.execute("SELECT ts FROM activity WHERE ts>=? AND ts<? AND idle=0 ORDER BY ts",
                                    (t0 - 18 * 3600, t1 + 30 * 3600))]
    gaps = [(b - a, a, b) for a, b in zip(ts, ts[1:]) if b - a >= gap]
    # sleep is the longest break; a trip out of the house is usually shorter
    w = max((g for g in gaps if t0 <= g[2] < t1), default=None)
    wake = w[2] if w else None
    after = wake if wake else t0
    # bed = start of the longest break that begins between 8pm and noon (sleep, not an afternoon out)
    night = lambda ts: time.localtime(ts).tm_hour >= 20 or time.localtime(ts).tm_hour < 12
    bd = max((g for g in gaps if after < g[1] < after + 30 * 3600 and g[1] > t0 + 6 * 3600 and night(g[1])), default=None)
    return wake, (bd[1] if bd else None)


def clean_stretch(rows, S=SAMPLE_SECONDS):
    """Longest run of being at the PC with no game/video/social stint of 60s+ and no break over 2 min.
    rows: (ts, app, title). Returns (seconds, start_ts)."""
    best, best_start = 0, None
    start = dstart = prev = None
    for r in rows:
        ts = r["ts"]
        if prev is not None and ts - prev > 120:
            start = dstart = None
        if start is None:
            start = ts
        if kind(r["app"], r["title"]):
            dstart = dstart or ts
            if ts - dstart >= 60:  # a real distraction: the clean run ended where it began
                if dstart - start > best:
                    best, best_start = dstart - start, start
                start = None
                continue
        else:
            dstart = None
        end = dstart or ts  # a blip that's still going doesn't count toward the clean run
        if end - start > best:
            best, best_start = end - start, start
        prev = ts
    return best, best_start


def _clock(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def day_facts(con, day: str):
    """Hard numbers for one day (5am `day` to 5am the next), from the 3s samples and the checks. None if no data."""
    from watcher import site_and_page  # lazy: watcher pulls in mss/anthropic
    y, m, d = map(int, day.split("-"))
    t0 = time.mktime((y, m, d, DAY_START_HOUR, 0, 0, 0, 0, -1))
    t1 = time.mktime((y, m, d + 1, DAY_START_HOUR, 0, 0, 0, 0, -1))
    rows = con.execute("SELECT ts, app, title FROM activity WHERE ts>=? AND ts<? AND idle=0 ORDER BY ts", (t0, t1)).fetchall()
    obs = [dict(o) for o in con.execute("SELECT * FROM observations WHERE ts_end>=? AND ts_end<? ORDER BY ts_end", (t0, t1))]
    for o in obs:  # a check after a long gap (sleep) spans hours; it only describes its last few minutes
        o["ts_start"] = max(o["ts_start"], o["ts_end"] - 900)
    if len(rows) < 20:
        return None
    S = SAMPLE_SECONDS
    work = [(o["ts_start"], o["ts_end"]) for o in obs if o["category"] in WORK]
    in_work = lambda ts: any(a <= ts < b for a, b in work)
    mins = Counter()
    sites = Counter()
    switches, prev_app = 0, None
    # distraction stints: a run of game/video/social samples >= 60s; counted as an interruption if it starts inside work
    interruptions, stint, stint_start, stint_kind = Counter(), 0, None, None
    prev_ts = None
    for r in rows:
        k = kind(r["app"], r["title"])
        if k:
            mins[k] += S
        if r["app"] != prev_app and prev_app is not None:
            switches += 1
        prev_app = r["app"]
        site, _ = site_and_page(r["app"] or "?", r["title"] or "")
        sites[_pretty(site)] += S
        contiguous = prev_ts is not None and r["ts"] - prev_ts <= 3 * S
        if k and contiguous and k == stint_kind:
            stint += S
        else:
            if stint >= 60 and in_work(stint_start):
                interruptions[stint_kind] += 1
            stint, stint_start, stint_kind = (S, r["ts"], k) if k else (0, None, None)
        prev_ts = r["ts"]
    if stint >= 60 and stint_start and in_work(stint_start):
        interruptions[stint_kind] += 1
    blocks = focus_blocks(obs)
    cs, cs_start = clean_stretch(rows)
    active = len(rows) * S
    wake, bed = sleep_bounds(con, t0, t1)
    first_work = min((a for a, _ in work if not wake or a >= wake), default=None)
    noise = {"ShellExperienceHost", "SearchHost", "explorer", "StartMenuExperienceHost", "ShellHost", "LockApp", "?", ""}
    return {
        "day": day,
        "active_min": round(active / 60),
        "woke": _clock(wake) if wake else None,
        "went_to_bed": _clock(bed) if bed else None,
        "first_work": _clock(first_work) if first_work else None,
        "work_min": round(sum(b - a for a, b in work) / 60),
        "deep_min": round(sum(b["seconds"] for b in blocks) / 60),
        "longest_clean_stretch": {"min": round(cs / 60), "start": _clock(cs_start)} if cs_start else None,
        "longest_block": ({"min": round(blocks[0]["seconds"] / 60), "start": _clock(blocks[0]["start"]),
                           "category": blocks[0]["category"]} if blocks else None),
        "game_min": round(mins["game"] / 60), "video_min": round(mins["video"] / 60), "social_min": round(mins["social"] / 60),
        "interruptions": {"game": interruptions["game"], "video": interruptions["video"], "social": interruptions["social"]},
        "switches_per_hour": round(switches / max(active / 3600, 0.25)),
        "avg_focus": round(sum(o["focus"] for o in obs) / len(obs), 1) if obs else None,
        "checks": len(obs),
        "top": [[s, round(v / 60)] for s, v in sites.most_common(15) if s not in noise and v >= 120][:10],
    }
