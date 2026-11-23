import { NextResponse } from "next/server";
import { sql } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const [status] = await sql`SELECT * FROM status WHERE id = 1`;
  const [control] = await sql`SELECT * FROM control WHERE id = 1`;
  const obsDays = await sql`SELECT day, avg(focus)::float AS focus, count(*)::int AS checks FROM observations GROUP BY day`;
  const appDays = await sql`SELECT day, sum(seconds)::int AS active FROM app_usage GROUP BY day`;
  const map = new Map<string, { day: string; focus: number | null; checks: number; active: number; deep: number }>();
  for (const r of appDays) map.set(r.day, { day: r.day, focus: null, checks: 0, active: r.active, deep: 0 });
  for (const r of obsDays) map.set(r.day, { ...(map.get(r.day) ?? { day: r.day, active: 0, deep: 0 }), focus: r.focus, checks: r.checks });
  // deep work = time in non-gaming checks with focus >= 7 (same rule as insights.focus_blocks on the PC)
  const cutoff = new Date(Date.now() - 31 * 864e5).toISOString().slice(0, 10);
  const deep = await sql`SELECT day, sum(ts_end - ts_start)::float AS s FROM observations WHERE day >= ${cutoff} AND focus >= 7 AND category NOT IN ('gaming', 'entertainment') GROUP BY day`;
  for (const r of deep) { const d = map.get(r.day); if (d) d.deep = Math.round(r.s); }
  const days = [...map.values()].sort((a, b) => (a.day < b.day ? 1 : -1)).slice(0, 30);
  const day = new URL(req.url).searchParams.get("day") || status?.day || days[0]?.day || null;
  const observations = day ? await sql`SELECT * FROM observations WHERE day = ${day} ORDER BY ts_start DESC` : [];
  const apps = day ? await sql`SELECT app, seconds FROM app_usage WHERE day = ${day} ORDER BY seconds DESC LIMIT 12` : [];
  let details: Record<string, unknown>[] = [];
  try { if (day) details = await sql`SELECT app, site, page, seconds FROM app_detail WHERE day = ${day} ORDER BY seconds DESC`; } catch {}
  return NextResponse.json({ now: Date.now() / 1000, status: status ?? null, control, day, days, observations, apps, details });
}
