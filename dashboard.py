"""Live local dashboard for the watcher: http://127.0.0.1:8765"""
import json
import sys
import time
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from insights import deep_work_streak, focus_blocks, week_trend
from common import ANALYZE_SECONDS, DASH_PORT, MODEL, SAMPLE_SECONDS, db, meta_get, meta_set, now

PORT = DASH_PORT
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


def state():
    con = db()
    try:
        return _state(con)
    finally:
        con.close()


def _state(con):
    t0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    apps, last = Counter(), None
    for r in con.execute("SELECT app,title,idle,ts FROM activity WHERE ts>=? ORDER BY ts", (t0,)):
        if not r["idle"]:
            apps[r["app"] or "?"] += SAMPLE_SECONDS
        last = r
    obs = con.execute("SELECT * FROM observations WHERE ts_end>=? ORDER BY ts_start DESC", (t0,)).fetchall()
    cats = Counter()
    for o in obs:
        cats[o["category"]] += o["ts_end"] - o["ts_start"]
    hb = float(meta_get(con, "heartbeat", 0))
    paused = meta_get(con, "paused") == "1"
    running = now() - hb < 20
    pending = con.execute("SELECT COUNT(*) c FROM shots WHERE analyzed=0").fetchone()["c"]
    last_an = float(meta_get(con, "last_analysis", now()))
    week = week_trend(con)
    blocks = focus_blocks(obs)
    return {
        "week": week,
        "deep_seconds": sum(b["seconds"] for b in blocks),
        "longest_block": blocks[0] if blocks else None,
        "streak": deep_work_streak(week),
        "status": "paused" if running and paused else "watching" if running else "stopped",
        "current": {"app": last["app"], "title": last["title"], "idle": bool(last["idle"])} if last else None,
        "active_seconds": sum(apps.values()),
        "apps": apps.most_common(10),
        "categories": cats.most_common(),
        "pending_shots": pending,
        "next_check": max(0, int(last_an + ANALYZE_SECONDS - now())),
        "checking": meta_get(con, "force_check") == "1",
        "model": MODEL,
        "cost": sum(o["input_tokens"] * 0.10 + o["output_tokens"] * 0.50 for o in obs) / 1e6,
        "observations": [
            {"start": o["ts_start"], "end": o["ts_end"], "category": o["category"], "focus": o["focus"],
             "summary": o["summary"], "tips": json.loads(o["tips_json"] or "[]")}
            for o in obs
        ],
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json", code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if ctype == "text/html":
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(b)

    def host_ok(self):
        # Blocks DNS-rebinding: a page on evil.com re-pointed at 127.0.0.1 still sends Host: evil.com
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def do_GET(self):
        if not self.host_ok():
            return self.send('{"error":"bad host"}', code=403)
        path = self.path.split("?")[0]
        if path == "/api/state":
            self.send(json.dumps(state()))
        elif path in ("/", "/index.html"):
            self.send(PAGE, "text/html")
        else:
            self.send('{"error":"not found"}', code=404)

    def do_POST(self):
        # CSRF: any website can fire a no-cors POST at 127.0.0.1. Require a custom header (forces a CORS
        # preflight we never answer) and, when the browser sends one, a same-origin Origin.
        origin = self.headers.get("Origin")
        if (not self.host_ok() or self.headers.get("X-Watcher") != "1"
                or (origin is not None and origin.split("//", 1)[-1] not in ALLOWED_HOSTS)):
            return self.send('{"error":"forbidden"}', code=403)
        con = db()
        try:
            if self.path == "/api/pause":
                meta_set(con, "paused", 1)
            elif self.path == "/api/resume":
                meta_set(con, "paused", 0)
            elif self.path == "/api/check":
                meta_set(con, "force_check", 1)
            else:
                return self.send('{"error":"not found"}', code=404)
        finally:
            con.close()
        self.send(json.dumps(state()))


PAGE = r"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Watcher</title>
<style>
:root{--bg:#f6f5f3;--card:#fff;--fg:#1c1917;--mut:#78716c;--line:#e7e5e4;--acc:#2563eb;--ok:#16a34a;--warn:#d97706;--bad:#dc2626;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f0e0d;--card:#1a1817;--fg:#ece9e6;--mut:#9c958f;--line:#2a2725;--acc:#6ea0ff;color-scheme:dark}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:20px;margin:0;letter-spacing:-.01em}
.pill{display:inline-flex;align-items:center;gap:7px;padding:4px 11px;border-radius:99px;background:var(--card);border:1px solid var(--line);font-size:13px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--mut)}
.watching .dot{background:var(--ok);box-shadow:0 0 0 0 var(--ok);animation:p 2s infinite}
.paused .dot{background:var(--warn)} .stopped .dot{background:var(--bad)}
@keyframes p{0%{box-shadow:0 0 0 0 rgb(22 163 74/.5)}70%{box-shadow:0 0 0 7px rgb(22 163 74/0)}100%{box-shadow:0 0 0 0 rgb(22 163 74/0)}}
.now{color:var(--mut);font-size:13px;flex:1;min-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.now b{color:var(--fg);font-weight:600}
button{font:inherit;font-size:13px;padding:6px 13px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button:hover{border-color:var(--mut)} button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
button:disabled{opacity:.5;cursor:default}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stat b{display:block;font-size:24px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat span{color:var(--mut);font-size:12.5px}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}
@media (max-width:860px){.grid{grid-template-columns:1fr}}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);margin:0 0 10px;font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:12px}
.obs-head{display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:12.5px;color:var(--mut)}
.chip{padding:1px 8px;border-radius:99px;background:var(--line);color:var(--fg);font-size:12px}
.focus{margin-left:auto;display:flex;align-items:center;gap:6px}
.meter{width:60px;height:6px;border-radius:3px;background:var(--line);overflow:hidden}.meter i{display:block;height:100%}
.tips{list-style:none;padding:0;margin:12px 0 0}
.tips li{border-left:3px solid var(--line);padding:3px 0 3px 12px;margin:9px 0}
.tips li.high{border-color:var(--bad)} .tips li.medium{border-color:var(--warn)}
.tips .why{color:var(--mut);font-size:12.5px;display:block;margin-top:2px}
.imp{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-right:6px}
.row{display:grid;grid-template-columns:110px 1fr 54px;gap:10px;align-items:center;margin:7px 0;font-size:13px}
.row .k{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row .v{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}
.bar{height:7px;border-radius:4px;background:var(--line);overflow:hidden}.bar i{display:block;height:100%;background:var(--acc)}
.empty{color:var(--mut);text-align:center;padding:40px 10px}
.spark{display:flex;align-items:flex-end;gap:3px;height:60px}.spark i{flex:1;min-width:4px;max-width:18px;border-radius:3px 3px 0 0}
.foot{color:var(--mut);font-size:12px;margin-top:6px}
.wk{display:grid;grid-template-columns:34px 1fr 50px;gap:8px;align-items:center;margin:6px 0;font-size:12.5px}
.wk .tb{position:relative;height:9px;background:var(--line);border-radius:5px;overflow:hidden}
.wk .tb i{position:absolute;left:0;top:0;bottom:0;border-radius:5px}.wk .tb .a{background:var(--acc);opacity:.3}.wk .tb .d{background:var(--ok)}
.wk.today span:first-child{font-weight:700}.wk .v{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}
</style>
<div class="wrap">
<header>
  <h1>watcher</h1>
  <span id="status" class="pill"><span class="dot"></span><span id="statusText">…</span></span>
  <span class="now" id="now"></span>
  <button id="toggle"></button>
  <button id="check" class="primary">Check now</button>
</header>
<div class="stats">
  <div class="stat"><b id="sActive">–</b><span>active today</span></div>
  <div class="stat"><b id="sFocus">–</b><span>avg focus</span></div>
  <div class="stat"><b id="sDeep">–</b><span id="sDeepL">deep work today</span></div>
  <div class="stat"><b id="sTips">–</b><span>tips today</span></div>
  <div class="stat"><b id="sNext">–</b><span id="sNextL">next check</span></div>
  <div class="stat"><b id="sCost">–</b><span>API cost today</span></div>
</div>
<div class="grid">
  <section><h2>Feed</h2><div id="feed"></div></section>
  <aside>
    <div class="card"><h2>This week</h2><div id="week"></div><div class="foot">faint = active · solid = deep work (focus 7+, not gaming)</div></div>
    <div class="card"><h2>Focus through the day</h2><div class="spark" id="spark"></div></div>
    <div class="card"><h2>By activity</h2><div id="cats"></div></div>
    <div class="card"><h2>By app</h2><div id="apps"></div></div>
    <div class="foot" id="foot"></div>
  </aside>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const dur=s=>{s=Math.round(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?`${h}h ${String(m).padStart(2,"0")}m`:`${m}m`};
const hm=t=>new Date(t*1000).toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
const fcol=f=>f>=7?"var(--ok)":f>=4?"var(--warn)":"var(--bad)";
let S=null,tick=0;
function bars(list){const tot=list.reduce((a,[,v])=>a+v,0);if(!tot)return'<div class="foot">No data yet.</div>';
  return list.map(([k,v])=>`<div class="row"><span class="k" title="${esc(k)}">${esc(String(k).replace(/\.exe$/i,"").replace(/_/g," "))}</span><span class="bar"><i style="width:${(100*v/tot).toFixed(1)}%"></i></span><span class="v">${dur(v)}</span></div>`).join("")}
function render(){
  if(!S)return; const st=S.status;
  $("status").className="pill "+st; $("statusText").textContent={watching:"Watching",paused:"Paused",stopped:"Not running"}[st];
  $("now").innerHTML=S.current&&st==="watching"?(S.current.idle?"Away from keyboard":`<b>${esc(S.current.app.replace(/\.exe$/i,""))}</b> · ${esc(S.current.title)}`):st==="stopped"?"Run start.bat to start watching":"";
  $("toggle").textContent=st==="paused"?"Resume":"Pause"; $("toggle").disabled=st==="stopped";
  $("check").disabled=st!=="watching"||S.checking; $("check").textContent=S.checking?"Checking…":"Check now";
  const O=S.observations, tips=O.flatMap(o=>o.tips);
  $("sActive").textContent=dur(S.active_seconds);
  $("sFocus").textContent=O.length?(O.reduce((a,o)=>a+o.focus,0)/O.length).toFixed(1):"–";
  $("sTips").textContent=tips.length;
  $("sDeep").textContent=dur(S.deep_seconds);
  $("sDeepL").textContent=S.streak?`deep work · ${S.streak}-day streak`:"deep work today";
  const mx=Math.max(1,...S.week.map(d=>d.active)), td=S.week.length?S.week[S.week.length-1].day:"";
  $("week").innerHTML=S.week.map(d=>`<div class="wk${d.day===td?" today":""}" title="${esc(d.day)} · focus ${d.focus??"–"} · ${d.checks} checks"><span>${new Date(d.day+"T12:00").toLocaleDateString([], {weekday:"short"})}</span><span class="tb"><i class="a" style="width:${(100*d.active/mx).toFixed(1)}%"></i><i class="d" style="width:${(100*d.deep/mx).toFixed(1)}%"></i></span><span class="v">${dur(d.deep)}</span></div>`).join("");
  countdown();
  $("sNextL").textContent=`next check · ${S.pending_shots} shot${S.pending_shots==1?"":"s"} queued`;
  $("sCost").textContent="$"+S.cost.toFixed(3);
  $("feed").innerHTML=O.length?O.map(o=>`<div class="card">
    <div class="obs-head"><span>${hm(o.start)} – ${hm(o.end)}</span><span class="chip">${esc(o.category.replace("_"," "))}</span>
    <span class="focus">focus ${o.focus}<span class="meter"><i style="width:${o.focus*10}%;background:${fcol(o.focus)}"></i></span></span></div>
    <div>${esc(o.summary)}</div>
    ${o.tips.length?`<ul class="tips">${o.tips.map(t=>`<li class="${t.impact}"><span class="imp">${t.impact}</span>${esc(t.tip)}<span class="why">${esc(t.why)}</span></li>`).join("")}</ul>`:""}
  </div>`).join(""):`<div class="card empty">No checks yet today. The first one lands within 10 minutes of activity, or hit <b>Check now</b>.</div>`;
  const rev=[...O].reverse();
  $("spark").innerHTML=rev.length?rev.map(o=>`<i title="${hm(o.start)} · focus ${o.focus}" style="height:${o.focus*10}%;background:${fcol(o.focus)}"></i>`).join(""):'<div class="foot">No checks yet.</div>';
  $("cats").innerHTML=bars(S.categories); $("apps").innerHTML=bars(S.apps);
  $("foot").textContent=`${S.model} · screenshots deleted after each check · data stays in data/watcher.db`;
}
function countdown(){if(!S)return;const nx=Math.max(0,S.next_check-tick);
  $("sNext").textContent=S.checking?"now":S.status==="watching"?`${Math.floor(nx/60)}:${String(nx%60).padStart(2,"0")}`:"–"}
async function load(){try{S=await (await fetch("/api/state")).json();tick=0;render()}catch(e){}}
async function post(p){S=await (await fetch(p,{method:"POST",headers:{"X-Watcher":"1"}})).json();tick=0;render()}
$("toggle").onclick=()=>post(S.status==="paused"?"/api/resume":"/api/pause");
$("check").onclick=()=>post("/api/check");
load(); setInterval(load,5000); setInterval(()=>{tick++;countdown()},1000);
</script>
"""


def main():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        srv = None  # already running
    if "--no-open" not in sys.argv:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    if srv:
        print(f"dashboard on http://127.0.0.1:{PORT}")
        srv.serve_forever()


if __name__ == "__main__":
    main()
