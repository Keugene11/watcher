import { NextResponse } from "next/server";
import { isIngestAuthed } from "@/lib/auth";
import { sql } from "@/lib/db";

let detailReady = false;

// The body comes from the PC, but window titles inside it are attacker-controlled text (any web page sets its
// own title), so everything is type-checked and length-capped before it is stored.
const str = (v: unknown, n = 300) => (typeof v === "string" ? v.slice(0, n) : "");
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const CATS = new Set(["coding", "gaming", "job_hunting", "browsing", "communication", "learning", "entertainment", "admin", "other"]);
const IMPACT = new Set(["low", "medium", "high"]);
type AnyObj = Record<string, unknown>;
const cleanTips = (t: unknown) => (Array.isArray(t) ? t.slice(0, 5) : []).map((x: AnyObj) => ({
  tip: str(x?.tip, 600), why: str(x?.why, 600), impact: IMPACT.has(x?.impact as string) ? x.impact : "low",
}));

// Called by the watcher on the PC every ~15s. Returns pending remote commands.
export async function POST(req: Request) {
  if (!isIngestAuthed(req)) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const b = await req.json().catch(() => null);
  if (!b || typeof b !== "object") return NextResponse.json({ error: "bad body" }, { status: 400 });
  const raw = (b.status ?? {}) as AnyObj;
  const s = {
    heartbeat: num(raw.heartbeat), day: DAY.test(String(raw.day)) ? String(raw.day) : null,
    app: str(raw.app, 120), title: str(raw.title, 200), idle: !!raw.idle, paused: !!raw.paused,
    next_check: Math.round(num(raw.next_check)), pending: Math.round(num(raw.pending)),
    checking: !!raw.checking, model: str(raw.model, 60),
  };
  await sql`INSERT INTO status (id, heartbeat, day, app, title, idle, paused, next_check, pending, checking, model)
    VALUES (1, ${s.heartbeat}, ${s.day}, ${s.app}, ${s.title}, ${s.idle}, ${s.paused}, ${s.next_check}, ${s.pending}, ${s.checking}, ${s.model})
    ON CONFLICT (id) DO UPDATE SET heartbeat=EXCLUDED.heartbeat, day=EXCLUDED.day, app=EXCLUDED.app, title=EXCLUDED.title,
      idle=EXCLUDED.idle, paused=EXCLUDED.paused, next_check=EXCLUDED.next_check, pending=EXCLUDED.pending,
      checking=EXCLUDED.checking, model=EXCLUDED.model`;

  for (const o of (Array.isArray(b.observations) ? b.observations.slice(0, 100) : []) as AnyObj[]) {
    if (!Number.isInteger(o.id) || !DAY.test(String(o.day))) continue;
    const cat = CATS.has(o.category as string) ? (o.category as string) : "other";
    const focus = Math.max(1, Math.min(10, Math.round(num(o.focus))));
    await sql`INSERT INTO observations (id, day, ts_start, ts_end, category, focus, summary, tips, input_tokens, output_tokens)
      VALUES (${o.id}, ${o.day}, ${num(o.ts_start)}, ${num(o.ts_end)}, ${cat}, ${focus}, ${str(o.summary, 1000)},
        ${JSON.stringify(cleanTips(o.tips))}::jsonb, ${Math.round(num(o.input_tokens))}, ${Math.round(num(o.output_tokens))})
      ON CONFLICT (id) DO NOTHING`;
  }

  const apps = (b.apps && typeof b.apps === "object" ? b.apps : {}) as Record<string, unknown>;
  const names = Object.keys(apps).filter((n) => n.length <= 120).slice(0, 200);
  if (s.day && names.length) {
    await sql`INSERT INTO app_usage (day, app, seconds)
      SELECT ${s.day}, a, sec FROM unnest(${names}::text[], ${names.map((n) => Math.round(num(apps[n])))}::int[]) AS t(a, sec)
      ON CONFLICT (day, app) DO UPDATE SET seconds = EXCLUDED.seconds`;
  }

  const details = Array.isArray(b.details)
    ? (b.details as unknown[][]).filter((d) => Array.isArray(d) && d.length === 4).slice(0, 300)
        .map((d) => [str(d[0], 120), str(d[1], 120), str(d[2], 200), Math.round(num(d[3]))] as const)
    : undefined;
  if (s.day && details) {
    if (!detailReady) {
      await sql`CREATE TABLE IF NOT EXISTS app_detail (day text, app text, site text, page text, seconds int, PRIMARY KEY (day, app, site, page))`;
      detailReady = true;
    }
    await sql`DELETE FROM app_detail WHERE day = ${s.day}`;
    // page titles are the most revealing data the cloud holds and the UI only shows 30 days: keep no more
    const cutoff = new Date(Date.parse(s.day + "T00:00:00Z") - 30 * 864e5).toISOString().slice(0, 10);
    await sql`DELETE FROM app_detail WHERE day < ${cutoff}`;
    if (details.length) {
      await sql`INSERT INTO app_detail (day, app, site, page, seconds)
        SELECT ${s.day}, a, si, pg, sec FROM unnest(${details.map((d) => d[0])}::text[], ${details.map((d) => d[1])}::text[],
          ${details.map((d) => d[2])}::text[], ${details.map((d) => d[3])}::int[]) AS t(a, si, pg, sec)
        ON CONFLICT DO NOTHING`;
    }
  }

  // per-day hard numbers computed on the PC (see insights.day_facts); fed to the daily feedback
  const facts = b.facts && typeof b.facts === "object" && !Array.isArray(b.facts) ? (b.facts as Record<string, unknown>) : {};
  const factDays = Object.keys(facts).filter((d) => DAY.test(d)).slice(0, 10);
  if (factDays.length) {
    await sql`CREATE TABLE IF NOT EXISTS day_facts (day text PRIMARY KEY, data jsonb, updated double precision)`;
    for (const d of factDays) {
      const json = JSON.stringify(facts[d]);
      if (!facts[d] || typeof facts[d] !== "object" || json.length > 8000) continue;
      await sql`INSERT INTO day_facts (day, data, updated) VALUES (${d}, ${json}::jsonb, ${Date.now() / 1000})
        ON CONFLICT (day) DO UPDATE SET data = EXCLUDED.data, updated = EXCLUDED.updated`;
    }
  }

  // hand over pending commands exactly once
  const [c] = await sql`WITH old AS (SELECT pause, force_check FROM control WHERE id = 1 FOR UPDATE),
    upd AS (UPDATE control SET pause = NULL, force_check = false WHERE id = 1)
    SELECT pause, force_check FROM old`;
  return NextResponse.json({ pause: c?.pause ?? null, force_check: !!c?.force_check });
}
