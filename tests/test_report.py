import json
import time
from datetime import datetime
from types import SimpleNamespace

import common
import insights
import report
import watcher


def o(start, mins, focus, cat="coding", summary="s"):
    return {"ts_start": start, "ts_end": start + mins * 60, "focus": focus, "category": cat, "summary": summary}


def test_focus_blocks_merge_and_split():
    t = 1_000_000
    obs = [o(t, 10, 8), o(t + 600, 10, 9), o(t + 1200, 10, 3), o(t + 1800, 10, 7), o(t + 6000, 10, 8)]
    b = insights.focus_blocks(obs)
    assert [x["seconds"] for x in b] == [1200, 600, 600]
    assert b[0]["avg_focus"] == 8.5 and b[0]["category"] == "coding"


def test_time_sinks():
    t = 0
    s = insights.time_sinks([o(t, 10, 3, "browsing", "HN"), o(t, 20, 2, "browsing", "X"), o(t, 10, 4, "gaming"), o(t, 10, 8)])
    assert s[0][0] == "browsing" and s[0][1] == 1800 and s[0][2] == ["HN", "X"]


def test_grouped_tips_collapses_rewordings():
    tips = [(1, {"tip": "Use Ctrl+R to search shell history", "impact": "low", "why": ""}),
            (2, {"tip": "Search shell history with Ctrl+R", "impact": "high", "why": ""}),
            (3, {"tip": "Hold econ to 50 gold before rolling", "impact": "medium", "why": ""})]
    g = insights.grouped_tips(tips, watcher.is_dup_tip)
    assert len(g) == 2
    assert g[0][1] == 2 and g[0][0]["impact"] == "high"


def test_deep_work_streak():
    mk = lambda *deep: [{"deep": d} for d in deep]  # noqa: E731
    assert insights.deep_work_streak(mk(0, 4000, 4000, 5000, 0)) == 3      # today empty doesn't break it
    assert insights.deep_work_streak(mk(4000, 0, 4000, 4000)) == 2
    assert insights.deep_work_streak(mk(0, 0)) == 0


def seed(con, now):
    today0 = common.day_start(now)
    rows = []
    for d in range(3):
        base = today0 - d * 86400 + 10 * 3600
        for i in range(6):
            con.execute("INSERT INTO observations(ts_start,ts_end,category,focus,summary,tips_json,input_tokens,output_tokens)"
                        " VALUES(?,?,?,?,?,?,?,?)",
                        (base + i * 600, base + (i + 1) * 600, "coding" if i < 4 else "browsing", 8 if i < 4 else 3,
                         f"<b>summary</b> {i}", json.dumps([{"tip": f"tip number {i} <script>x</script>", "why": "w",
                                                            "impact": "high" if i == 0 else "low"}]), 1000, 100))
        rows += [(base + k * 3, "Code.exe", "a.py", 0) for k in range(600)]
    con.executemany("INSERT INTO activity VALUES(?,?,?,?)", rows)
    con.commit()


def test_week_trend(con):
    now = time.time()
    seed(con, now)
    tr = insights.week_trend(con, now=now)
    assert len(tr) == 7 and tr[-1]["day"] == time.strftime("%Y-%m-%d", time.localtime(now))
    assert tr[-1]["checks"] == 6 and tr[-1]["deep"] == 2400 and tr[-1]["active"] == 1800
    assert tr[0]["checks"] == 0 and tr[0]["focus"] is None


def test_week_trend_uses_rollup_after_prune(con):
    now = time.time()
    seed(con, now)
    common.rollup_and_prune(con, keep_days=0, now_ts=now)
    tr = insights.week_trend(con, now=now)
    assert tr[-2]["active"] == 1800  # yesterday now comes from activity_daily


class FakeClient:
    def __init__(self, text):
        self.text, self.calls = text, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_report_builds_and_sanitizes(con):
    now = time.time()
    seed(con, now)
    evil = '<p>Good day.</p><img src=x onerror=alert(1)><script>alert(2)</script><b onclick="x">bold</b><ul><li>a</li></ul>'
    c = FakeClient(evil)
    page = report.build_report(con, datetime.fromtimestamp(now), c, now=now)
    assert "<p>Good day.</p>" in page and "<ul><li>a</li></ul>" in page
    deb = page.split("<h2>Debrief</h2>")[1].split("<h2>")[0]
    assert "<img" not in deb and "<script>" not in deb and "&lt;b onclick" in deb
    assert "<script>x</script>" not in page  # tips escaped
    assert "Deep work" in page and "Last 7 days" in page
    assert c.calls[0]["model"] == common.MODEL and "haiku" in common.MODEL
    prompt = c.calls[0]["messages"][0]["content"]
    assert "Deep-work blocks" in prompt and "Last 7 days" in prompt


def test_report_without_ai_or_data(con):
    page = report.build_report(con, datetime.now(), None)
    assert "Not enough data yet" in page


def test_report_survives_api_error(con):
    now = time.time()
    seed(con, now)

    class Boom:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            raise RuntimeError("<script>bad</script>")
    page = report.build_report(con, datetime.fromtimestamp(now), Boom(), now=now)
    assert "Debrief failed" in page and "<script>bad" not in page


def test_sanitize_html():
    assert report.sanitize_html("<p>x</p><B>y</B>") == "<p>x</p><b>y</b>"
    assert report.sanitize_html('<a href="javascript:1">z</a>') == "&lt;a href=&quot;javascript:1&quot;&gt;z&lt;/a&gt;"
    assert report.sanitize_html('<b onclick="x">') == "&lt;b onclick=&quot;x&quot;&gt;"


def test_gaming_is_not_deep_work():
    assert insights.focus_blocks([o(0, 10, 9, "gaming"), o(600, 10, 9, "entertainment")]) == []
    assert insights.focus_blocks([o(0, 10, 9, "gaming"), o(600, 10, 9, "coding")])[0]["seconds"] == 600


def test_day_facts(con):
    import insights
    S = common.SAMPLE_SECONDS
    t0 = time.mktime((2026, 3, 10, 15, 0, 0, 0, 0, -1))  # 3pm
    rows = []
    t = t0
    for _ in range(600):  # 30 min coding
        rows.append((t, "Code.exe", "a.py - Visual Studio Code", 0)); t += S
    for _ in range(100):  # 5 min of CS2 in the middle of work
        rows.append((t, "cs2.exe", "Counter-Strike 2", 0)); t += S
    for _ in range(200):  # 10 min YouTube
        rows.append((t, "chrome.exe", "lofi - YouTube - Google Chrome", 0)); t += S
    con.executemany("INSERT INTO activity(ts,app,title,idle) VALUES(?,?,?,?)", rows)
    for a, b in [(t0, t0 + 600), (t0 + 1500, t0 + 2400)]:  # two 10-15 min coding checks; the 2nd covers 15:25-15:40
        con.execute("INSERT INTO observations(ts_start,ts_end,category,focus,summary,tips_json,input_tokens,output_tokens)"
                    " VALUES(?,?,?,?,?,?,?,?)", (a, b, "coding", 8, "x", "[]", 0, 0))
    con.commit()
    f = insights.day_facts(con, "2026-03-10")
    assert f["active_min"] == 45 and f["game_min"] == 5 and f["video_min"] == 10
    assert f["interruptions"]["game"] == 1 and f["interruptions"]["video"] == 1
    assert f["longest_clean_stretch"]["min"] == 30 and f["longest_clean_stretch"]["start"] == "15:00"
    assert f["first_work"] == "15:00"
    assert ["VS Code", 30] in f["top"] and ["CS2", 5] in f["top"]
