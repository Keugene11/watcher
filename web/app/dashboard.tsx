"use client";
import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Clock, Eye, Monitor, Moon, Pause, Play, RefreshCw, Sparkles, Sun } from "lucide-react";

type Tip = { tip: string; why: string; impact: "low" | "medium" | "high" };
type Obs = { id: number; ts_start: number; ts_end: number; category: string; focus: number; summary: string; tips: Tip[]; input_tokens: number; output_tokens: number };
type Status = { heartbeat: number; day: string; app: string; title: string; idle: boolean; paused: boolean; next_check: number; pending: number; checking: boolean; model: string };
type Day = { day: string; focus: number | null; checks: number; active: number; deep?: number };
type State = {
  now: number; status: Status | null; control: { pause: boolean | null; force_check: boolean };
  day: string | null; days: Day[]; observations: Obs[]; apps: { app: string; seconds: number }[];
  details?: Detail[];
};
type Detail = { app: string; site: string; page: string; seconds: number };
type Debrief = { lines?: string[] };

const dur = (s: number) => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`; };
const hm = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const fcol = (f: number) => (f >= 7 ? "var(--ok)" : f >= 5 ? "var(--warn)" : "var(--bad)");
const clean = (a: string) => a.replace(/\.exe$/i, "").replace(/_/g, " ");
const ago = (s: number) => (s < 90 ? `${Math.round(s)}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`);
const rank = { high: 0, medium: 1, low: 2 } as const;

function dayName(d: string, today?: string, long = false) {
  const date = new Date(d + "T12:00");
  if (today) {
    const diff = Math.round((new Date(today + "T12:00").getTime() - date.getTime()) / 864e5);
    if (diff === 0) return long ? `Today, ${date.toLocaleDateString([], { month: "long", day: "numeric" })}` : "Today";
    if (diff === 1) return long ? `Yesterday, ${date.toLocaleDateString([], { month: "long", day: "numeric" })}` : "Yesterday";
  }
  return date.toLocaleDateString([], long ? { weekday: "long", month: "long", day: "numeric" } : { weekday: "short", month: "short", day: "numeric" });
}

function Bars({ list }: { list: [string, number][] }) {
  list = list.filter(([, v]) => v >= 60);
  const tot = list.reduce((a, [, v]) => a + v, 0);
  if (!tot) return <div className="foot">No data yet.</div>;
  return <>{list.map(([k, v]) => (
    <div className="row" key={k}>
      <span className="k" title={k}>{clean(k)}</span>
      <span className="bar"><i style={{ width: `${(100 * v) / tot}%` }} /></span>
      <span className="v num">{dur(v)}</span>
    </div>
  ))}</>;
}


function TimeSpent({ apps: allApps, details: allDetails, day }: { apps: { app: string; seconds: number }[]; details: Detail[]; day: string }) {
  const apps = allApps.filter((a) => a.seconds >= 60);
  const details = allDetails.filter((d) => d.seconds >= 60);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => setOpen({}), [day]);
  const total = apps.reduce((a, r) => a + r.seconds, 0);
  if (!total) return <section className="card"><h2 className="label"><Clock size={14} />Where your time went</h2><div className="foot">No activity logged yet.</div></section>;
  const max = apps[0]?.seconds || 1;
  const sitesFor = (app: string) => {
    const m = new Map<string, { seconds: number; pages: { page: string; seconds: number }[] }>();
    for (const d of details) if (d.app === app) {
      const e = m.get(d.site) ?? { seconds: 0, pages: [] };
      e.seconds += d.seconds; e.pages.push({ page: d.page, seconds: d.seconds }); m.set(d.site, e);
    }
    return [...m.entries()].sort((a, b) => b[1].seconds - a[1].seconds);
  };
  return (
    <section className="card">
      <h2 className="label"><Clock size={14} />Where your time went</h2>
      <div className="tlist">
        {apps.map((a) => {
          const sites = sitesFor(a.app);
          const expandable = sites.length > 1 || (sites.length === 1 && sites[0][0] !== a.app);
          const isOpen = open[a.app] ?? false;
          return (
            <div key={a.app} className="tapp">
              <button className="trow" disabled={!expandable} aria-expanded={isOpen} onClick={() => setOpen({ ...open, [a.app]: !isOpen })}>
                <ChevronRight size={14} className={`chev ${isOpen ? "on" : ""} ${expandable ? "" : "hide"}`} />
                <span className="tname">{clean(a.app)}</span>
                <span className="tbar"><i style={{ width: `${(100 * a.seconds) / max}%` }} /></span>
                <span className="tval num">{dur(a.seconds)}</span>
                <span className="tpct num">{Math.round((100 * a.seconds) / total)}%</span>
              </button>
              {isOpen && (
                <div className="tsites">
                  {sites.slice(0, 15).map(([site, e]) => (
                    <div key={site} className="tsite">
                      <div className="tsrow">
                        <span className="tname">{site}</span>
                        <span className="tbar sm"><i style={{ width: `${(100 * e.seconds) / a.seconds}%` }} /></span>
                        <span className="tval num">{dur(e.seconds)}</span>
                      </div>
                      {(e.pages.length > 1 || e.pages[0]?.page !== site) && (
                        <ul className="tpages">
                          {e.pages.slice(0, 4).map((p, i) => <li key={i}><span>{p.page}</span><span className="num">{dur(p.seconds)}</span></li>)}
                          {e.pages.length > 4 && <li className="foot">+{e.pages.length - 4} more</li>}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {!details.length && <div className="foot" style={{ marginTop: 10 }}>Per-site breakdown starts once the watcher on your PC syncs it.</div>}
    </section>
  );
}

/** Days in a row (ending at `today`, or the day before if today has none yet) with 1h+ of deep work. */
function streak(days: Day[], today: string) {
  const deep = new Map(days.map((d) => [d.day, d.deep ?? 0]));
  const step = (d: string) => new Date(new Date(d + "T12:00").getTime() - 864e5).toLocaleDateString("en-CA");
  let d = today, n = 0;
  if ((deep.get(d) ?? 0) < 3600) d = step(d);
  while ((deep.get(d) ?? 0) >= 3600) { n++; d = step(d); }
  return n;
}

function Week({ days, shown, onPick }: { days: Day[]; shown: string; onPick: (d: string) => void }) {
  const last = [...days].sort((a, b) => (a.day < b.day ? -1 : 1)).slice(-7);
  if (!last.length) return <div className="foot">No days yet.</div>;
  const max = Math.max(1, ...last.map((d) => d.active));
  return (
    <>
      {last.map((d) => (
        <button key={d.day} className={`wk ${d.day === shown ? "on" : ""}`} onClick={() => onPick(d.day)}
          title={`${d.day} · active ${dur(d.active)} · deep ${dur(d.deep ?? 0)} · focus ${d.focus?.toFixed(1) ?? "–"}`}>
          <span>{new Date(d.day + "T12:00").toLocaleDateString([], { weekday: "short" })}</span>
          <span className="wbar"><i className="a" style={{ width: `${(100 * d.active) / max}%` }} /><i className="d" style={{ width: `${(100 * (d.deep ?? 0)) / max}%` }} /></span>
          <span className="num">{dur(d.deep ?? 0)}</span>
        </button>
      ))}
      <div className="foot">faint = active · solid = deep work (focus 7+, not gaming)</div>
    </>
  );
}

type Theme = "system" | "light" | "dark";
function ThemeToggle() {
  const [t, setT] = useState<Theme>("system");
  useEffect(() => { try { const v = localStorage.getItem("theme"); if (v === "light" || v === "dark") setT(v); } catch {} }, []);
  function next() {
    const n: Theme = t === "system" ? "light" : t === "light" ? "dark" : "system";
    setT(n);
    const el = document.documentElement;
    if (n === "system") delete el.dataset.theme; else el.dataset.theme = n;
    try { if (n === "system") localStorage.removeItem("theme"); else localStorage.setItem("theme", n); } catch {}
  }
  const Icon = t === "light" ? Sun : t === "dark" ? Moon : Monitor;
  return <button className="icon" onClick={next} title={`Theme: ${t} (click to change)`} aria-label={`Theme: ${t}`}><Icon size={15} /></button>;
}

function DebriefCard({ day, count }: { day: string; count: number }) {
  const [d, setD] = useState<{ debrief: Debrief | null; obs_count?: number; created?: number } | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!count) { setD({ debrief: null }); return; }
    let live = true;
    setLoading(true);
    fetch(`/api/debrief?day=${day}`, { cache: "no-store" }).then((r) => r.json()).then((j) => { if (live) setD(j); }).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [day, count]);

  const b = d?.debrief?.lines?.length ? d.debrief : null; // older cached formats have no lines
  return (
    <section className="card debrief">
      <h2 className="label"><Sparkles size={14} />Daily feedback</h2>
      {!b && (loading || !d) ? (
        <><div className="skel" style={{ width: "80%", height: 20 }} /><div className="skel" style={{ width: "95%" }} /><div className="skel" style={{ width: "70%" }} /><div className="foot">Claude is reading the day…</div></>
      ) : !b ? (
        <div className="foot">No feedback yet. It gets written once the watcher has a few checks for this day.</div>
      ) : (
        <>
          <ol className="fixes">
            {b.lines!.map((x, i) => <li key={i}><div><b>{x}</b></div></li>)}
          </ol>
          <div className="meta">
            From measured time vs your usual · {d?.obs_count ?? count} checks{d?.created ? ` · updated ${hm(d.created)}` : ""}{loading ? " · refreshing…" : ""}
          </div>
        </>
      )}
    </section>
  );
}

export default function Dashboard() {
  const [S, setS] = useState<State | null>(null);
  const [day, setDay] = useState<string>("");
  const [tick, setTick] = useState(0);
  const [allTips, setAllTips] = useState(false);
  const [allEv, setAllEv] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch(`/api/state${day ? `?day=${day}` : ""}`, { cache: "no-store" });
    if (r.status === 401) { location.href = "/login"; return; }
    if (r.ok) { setS(await r.json()); setTick(0); }
  }, [day]);

  useEffect(() => { load(); const a = setInterval(load, 10000); return () => clearInterval(a); }, [load]);
  useEffect(() => { const a = setInterval(() => setTick((t) => t + 1), 1000); return () => clearInterval(a); }, []);
  useEffect(() => { setAllTips(false); setAllEv(false); }, [day]);

  async function control(action: "pause" | "resume" | "check") {
    await fetch("/api/control", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action }) });
    load();
  }

  if (!S) return <div className="wrap"><div className="empty">Loading…</div></div>;

  const st = S.status;
  const age = st ? S.now - st.heartbeat + tick : Infinity;
  const status = !st || age > 90 ? "stopped" : st.paused ? "paused" : "watching";
  const syncing = S.control?.pause !== null && S.control?.pause !== undefined;
  const O = S.observations;
  const shown = S.day ?? "";
  const tips = O.flatMap((o) => o.tips.map((t) => ({ ...t, at: o.ts_start }))).sort((a, b) => rank[a.impact] - rank[b.impact] || b.at - a.at);
  const cost = O.reduce((a, o) => a + o.input_tokens * 0.1 + o.output_tokens * 0.5, 0) / 1e6;
  const cats = new Map<string, number>();
  for (const o of O) cats.set(o.category.replace("_", " "), (cats.get(o.category.replace("_", " ")) ?? 0) + (o.ts_end - o.ts_start));
  const active = S.apps.reduce((a, r) => a + r.seconds, 0);
  const avg = O.length ? O.reduce((a, o) => a + o.focus, 0) / O.length : null;
  const nx = st ? Math.max(0, st.next_check - Math.round(S.now - st.heartbeat) - tick) : 0;
  const checking = st?.checking || S.control?.force_check;
  const asc = [...O].reverse();
  const evs = allEv ? O : O.slice(0, 8);
  const shownDay = S.days.find((d) => d.day === shown);
  const deepSec = shownDay?.deep ?? O.filter((o) => o.focus >= 7 && o.category !== "gaming" && o.category !== "entertainment").reduce((a, o) => a + o.ts_end - o.ts_start, 0);
  const streakDays = st?.day ? streak(S.days, st.day) : 0;

  return (
    <div className="wrap">
      <header>
        <span className="brand"><Eye size={19} />watcher</span>
        <span className={`pill ${status}`}><span className="dot" />{{ watching: "Watching", paused: "Paused", stopped: "PC offline" }[status]}</span>
        <span className="now">
          {status === "watching" && st && (st.idle ? "Away from keyboard" : <><b>{clean(st.app)}</b> · {st.title}</>)}
          {status === "stopped" && st && `Last seen ${ago(age)}`}
          {status === "watching" && !checking && <> · next check in <span className="num">{Math.floor(nx / 60)}:{String(nx % 60).padStart(2, "0")}</span></>}
        </span>
        <div className="actions">
          <button disabled={status === "stopped" || syncing} onClick={() => control(status === "paused" ? "resume" : "pause")}>
            {status === "paused" ? <Play size={14} /> : <Pause size={14} />}
            {syncing ? "Sending…" : status === "paused" ? "Resume" : "Pause"}
          </button>
          <button className="primary" disabled={status !== "watching" || !!checking} onClick={() => control("check")}>
            <RefreshCw size={14} className={checking ? "spin" : ""} />{checking ? "Checking…" : "Check now"}
          </button>
          <ThemeToggle />
        </div>
      </header>

      {S.days.length > 0 && (
        <nav className="days" aria-label="Days">
          {S.days.map((d) => (
            <button key={d.day} className={`daychip ${d.day === shown ? "on" : ""}`} onClick={() => setDay(d.day === st?.day ? "" : d.day)}>
              <span className="dn">{dayName(d.day, st?.day)}</span>
              <span className="ds">
                {d.focus !== null && <span className="fdot" style={{ background: fcol(d.focus) }} />}
                {d.focus !== null ? `focus ${d.focus.toFixed(1)}` : "no checks"} · {dur(d.active)}
              </span>
            </button>
          ))}
        </nav>
      )}

      <div className="dayhead">
        <h1>{shown ? dayName(shown, st?.day, true) : "No data yet"}</h1>
        <div className="stats">
          <div><b className="num">{dur(active)}</b>active</div>
          <div><b className="num" style={{ color: avg !== null ? fcol(avg) : undefined }}>{avg !== null ? avg.toFixed(1) : "–"}</b>avg focus</div>
          <div><b className="num">{dur(deepSec)}</b>deep work{streakDays > 0 && shown === st?.day ? ` · ${streakDays}d streak` : ""}</div>
          <div><b className="num">{O.length}</b>checks</div>
          <div><b className="num">{tips.length}</b>tips</div>
          <div><b className="num">${cost.toFixed(2)}</b>API cost</div>
        </div>
      </div>

      <div className="grid">
        <main className="col">
          {shown && <DebriefCard day={shown} count={O.length} />}
          <TimeSpent apps={S.apps} details={S.details ?? []} day={shown} />

          <section className="card">
            <h2 className="label">Tips · most important first</h2>
            {tips.length ? (
              <>
                <ul className="tiplist">
                  {(allTips ? tips : tips.slice(0, 6)).map((t, i) => (
                    <li key={i}>
                      <span className={`imp ${t.impact}`}>{t.impact}</span>
                      <span>{t.tip}<span className="at num">{hm(t.at)}</span></span>
                      {t.why && <span className="why">{t.why}</span>}
                    </li>
                  ))}
                </ul>
                {tips.length > 6 && <button className="more" onClick={() => setAllTips(!allTips)}>{allTips ? "Show fewer" : `Show all ${tips.length} tips`}</button>}
              </>
            ) : <div className="foot">No tips yet for this day.</div>}
          </section>

          <section className="card">
            <h2 className="label">Timeline · a check every 5 minutes</h2>
            {O.length ? (
              <>
                {evs.map((o) => (
                  <div className="ev" key={o.id}>
                    <span className="when num">{hm(o.ts_start)}</span>
                    <div>
                      <div className="evhead">
                        <span className="chip">{o.category.replace("_", " ")}</span>
                        <span>focus {o.focus}</span>
                        <span className="meter"><i style={{ width: `${o.focus * 10}%`, background: fcol(o.focus) }} /></span>
                      </div>
                      <div>{o.summary}</div>
                      {o.tips.length > 0 && (
                        <ul>{o.tips.map((t, i) => <li key={i}><span className={`imp ${t.impact}`}>{t.impact}</span><span>{t.tip}</span></li>)}</ul>
                      )}
                    </div>
                  </div>
                ))}
                {O.length > 8 && <button className="more" onClick={() => setAllEv(!allEv)}>{allEv ? "Show fewer" : `Show all ${O.length} checks`}</button>}
              </>
            ) : <div className="empty">No checks yet. The first one lands within 5 minutes of activity.</div>}
          </section>
        </main>

        <aside className="col">
          <section className="card"><h2 className="label">Focus through the day</h2>
            {asc.length ? <>
              <div className="spark">{asc.map((o) => <i key={o.id} title={`${hm(o.ts_start)} · focus ${o.focus}`} style={{ height: `${o.focus * 10}%`, background: fcol(o.focus) }} />)}</div>
              <div className="axis num"><span>{hm(asc[0].ts_start)}</span><span>{hm(asc[asc.length - 1].ts_end)}</span></div>
            </> : <div className="foot">No checks yet.</div>}
          </section>
          <section className="card"><h2 className="label">Last 7 days</h2><Week days={S.days} shown={shown} onPick={(d) => setDay(d === st?.day ? "" : d)} /></section>
          <section className="card"><h2 className="label">By activity</h2><Bars list={[...cats.entries()].sort((a, b) => b[1] - a[1])} /></section>
          <div className="foot">{st?.model ?? ""} · screenshots stay on your PC; only summaries and tips sync here</div>
        </aside>
      </div>
    </div>
  );
}
