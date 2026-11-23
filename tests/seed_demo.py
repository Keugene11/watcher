"""Fill a throwaway data dir with a fake week of activity (never real data). Used by the Playwright tests and
the demo videos.

    WATCHER_DATA_DIR=C:/tmp/demo python tests/seed_demo.py [--push http://localhost:3999 TOKEN]
"""
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
assert os.getenv("WATCHER_DATA_DIR"), "set WATCHER_DATA_DIR to a temp dir; this never seeds the real DB"
os.environ["WATCHER_CLOUD_URL"] = ""
import common  # noqa: E402

BLOCKS = [  # (app, titles, category, focus range, minutes)
    ("WindowsTerminal.exe", ["claude - understudy", "claude - watcher", "pnpm test - understudy"], "coding", (7, 9), 70),
    ("Code.exe", ["route.ts - understudy - Visual Studio Code", "watcher.py - watcher - Visual Studio Code"], "coding", (6, 9), 40),
    ("chrome.exe", ["Messaging | LinkedIn - Google Chrome", "Simplify | Jobs - Google Chrome",
                    "Work at a Startup - Y Combinator - Google Chrome"], "job_hunting", (5, 8), 45),
    ("chrome.exe", ["Hacker News - Google Chrome", "(1) Home / X - Google Chrome",
                    "Dalton Caldwell office hours - YouTube - Google Chrome"], "browsing", (3, 5), 35),
    ("League of Legends.exe", ["Teamfight Tactics"], "gaming", (5, 7), 40),
    ("cs2.exe", ["Counter-Strike 2"], "gaming", (4, 7), 30),
]
TIPS = {
    "coding": [("Run the failing test alone with `pnpm vitest -t name` instead of the whole suite each loop", "high",
                "You re-ran the full suite 4 times for one failing test."),
               ("Give Claude the stack trace and file path in one prompt; you pasted them in three turns", "medium",
                "Three back-to-back short prompts in the terminal."),
               ("Use Ctrl+P to jump files instead of the explorer tree", "low", "Clicked through 5 folders to open route.ts.")],
    "job_hunting": [("Batch the LinkedIn DMs: write one template per company type, then personalize line 1 only", "high",
                     "Spent 12 min writing a single DM from scratch."),
                    ("Filter Work at a Startup by 'NYC + seed/Series A' before scrolling", "medium",
                     "Scrolled past a lot of remote/late-stage listings.")],
    "browsing": [("HN + X for 35 min with nothing saved: set a 10-min cap or close the tab", "medium",
                  "Bounced between HN and X without opening a link.")],
    "gaming": [("You rolled to 0 gold at stage 3-2 on a 4-1 comp; hold econ to 50 and level at 4-1", "high",
                "Gold went 34 -> 0 at 3-2 with a weak board."),
               ("Stop peeking mid on eco rounds; stack B with the team", "medium", "Died first on 3 eco rounds.")],
}
SUMMARY = {
    "coding": "Driving Claude Code in the terminal on {t}, reviewing diffs in VS Code.",
    "job_hunting": "Job hunting: {t}.",
    "browsing": "Browsing {t}.",
    "gaming": "Playing {t}.",
}


def seed(days=7, now=None):
    rnd = random.Random(7)
    now = now or time.time()
    con = common.db()
    con.executescript("DELETE FROM activity; DELETE FROM observations; DELETE FROM shots; DELETE FROM activity_daily;"
                      "DELETE FROM meta;")
    today0 = common.day_start(now)
    used_tips = set()
    for d in range(days - 1, -1, -1):
        t = today0 - d * 86400 + 11 * 3600 + rnd.randint(0, 3600)
        if d == 0:
            t = max(today0 + 60, now - 6 * 3600)
        end = now - 60 if d == 0 else t + rnd.randint(5, 9) * 3600
        order = BLOCKS[:]
        rnd.shuffle(order)
        i = 0
        while t < end:
            app, titles, cat, (flo, fhi), mins = order[i % len(order)]
            i += 1
            mins = int(mins * rnd.uniform(0.5, 1.3))
            seg_end = min(end, t + mins * 60)
            w0 = t
            rows = []
            while t < seg_end:
                title = rnd.choice(titles)
                rows.append((t, app, title, int(rnd.random() < 0.05)))
                t += common.SAMPLE_SECONDS
            if d == 0 or d == 1:
                con.executemany("INSERT INTO activity VALUES(?,?,?,?)", rows)
            else:
                con.execute("INSERT INTO activity_daily(day,app,seconds) VALUES(strftime('%Y-%m-%d',?,'unixepoch','localtime'),?,?)"
                            " ON CONFLICT(day,app) DO UPDATE SET seconds=seconds+excluded.seconds",
                            (w0, app, sum(1 for r in rows if not r[3]) * common.SAMPLE_SECONDS))
            # one observation per 10 min of the block
            k = w0
            while k + 600 <= seg_end:
                pool = TIPS.get(cat, [])
                tips = []
                if pool and rnd.random() < 0.45:
                    tip = rnd.choice(pool)
                    if (d, tip[0]) not in used_tips:
                        used_tips.add((d, tip[0]))
                        tips.append({"tip": tip[0], "impact": tip[1], "why": tip[2]})
                label = rnd.choice(titles).replace(" - Google Chrome", "").replace(" - Visual Studio Code", "")
                con.execute("INSERT INTO observations(ts_start,ts_end,category,focus,summary,tips_json,input_tokens,"
                            "output_tokens) VALUES(?,?,?,?,?,?,?,?)",
                            (k, k + 600, cat, rnd.randint(flo, fhi), SUMMARY[cat].format(t=label), json.dumps(tips),
                             rnd.randint(6000, 9000), rnd.randint(150, 400)))
                k += 600
            t = seg_end + rnd.randint(2, 20) * 60
    common.meta_set(con, "rolled_until", today0 - 86400)
    common.meta_set(con, "heartbeat", now)
    common.meta_set(con, "last_analysis", now - 200)
    common.meta_set(con, "paused", 0)
    con.commit()
    return con


def push(con, base, token):
    import urllib.request
    import watcher
    os.environ["WATCHER_CLOUD_URL"], os.environ["INGEST_TOKEN"] = base, token
    # push every observation (the PC only sends new ones; this backfills the demo week)
    while True:
        cmd = watcher.sync_once(con)
        left = con.execute("SELECT COUNT(*) FROM observations WHERE id>?", (int(common.meta_get(con, "synced_obs", 0)),)).fetchone()[0]
        if not left:
            break
    # backfill per-day app totals for the past days, as the PC would have sent them on those days
    for r in con.execute("SELECT DISTINCT day FROM activity_daily"):
        apps = {a["app"]: a["seconds"] for a in con.execute("SELECT app, seconds FROM activity_daily WHERE day=?", (r["day"],))}
        body = {"status": watcher.build_sync_body(con)["status"] | {"day": r["day"]}, "observations": [], "apps": apps}
        req = urllib.request.Request(base.rstrip("/") + "/api/ingest", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    watcher.sync_once(con)  # leave status pointing at today
    return cmd


def serve(con):
    """Run the real local dashboard on WATCHER_DASH_PORT and play a fake watcher: keep the heartbeat fresh and answer
    'Check now' with a new observation a few seconds later."""
    import threading
    from http.server import ThreadingHTTPServer
    import dashboard
    srv = ThreadingHTTPServer(("127.0.0.1", dashboard.PORT), dashboard.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("demo dashboard on", dashboard.PORT, flush=True)
    asked = None
    while True:
        common.meta_set(con, "heartbeat", time.time())
        if common.meta_get(con, "force_check") == "1":
            asked = asked or time.time()
            if time.time() - asked > 3:
                t = time.time()
                con.execute("INSERT INTO observations(ts_start,ts_end,category,focus,summary,tips_json,input_tokens,"
                            "output_tokens) VALUES(?,?,?,?,?,?,?,?)",
                            (t - 200, t, "coding", 9, "Shipping the watcher test suite with Claude Code; tests green.",
                             json.dumps([{"tip": "Pipe pytest -x output straight into Claude instead of pasting it",
                                          "impact": "high", "why": "Copied the failure from one terminal to another."}]),
                             7000, 250))
                common.meta_set(con, "force_check", 0)
                common.meta_set(con, "last_analysis", t)
                asked = None
        time.sleep(1)


if __name__ == "__main__":
    c = seed()
    print("seeded", c.execute("SELECT COUNT(*) FROM observations").fetchone()[0], "observations into", common.DB_PATH)
    if "--push" in sys.argv:
        i = sys.argv.index("--push")
        push(c, sys.argv[i + 1], sys.argv[i + 2])
        print("pushed to", sys.argv[i + 1])
    if "--serve" in sys.argv:
        serve(c)
