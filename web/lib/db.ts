import { neon } from "@neondatabase/serverless";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
export type Sql = (strings: TemplateStringsArray, ...values: unknown[]) => Promise<Row[]>;

export const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS status (
    id int PRIMARY KEY DEFAULT 1, heartbeat double precision, day text, app text, title text, idle boolean,
    paused boolean, next_check int, pending int, checking boolean, model text)`,
  `CREATE TABLE IF NOT EXISTS control (id int PRIMARY KEY DEFAULT 1, pause boolean, force_check boolean DEFAULT false)`,
  `INSERT INTO control (id) VALUES (1) ON CONFLICT DO NOTHING`,
  `CREATE TABLE IF NOT EXISTS observations (
    id bigint PRIMARY KEY, day text, ts_start double precision, ts_end double precision, category text, focus int,
    summary text, tips jsonb, input_tokens int, output_tokens int)`,
  `CREATE INDEX IF NOT EXISTS observations_day ON observations(day)`,
  `CREATE TABLE IF NOT EXISTS app_usage (day text, app text, seconds int, PRIMARY KEY (day, app))`,
  `CREATE TABLE IF NOT EXISTS app_detail (day text, app text, site text, page text, seconds int, PRIMARY KEY (day, app, site, page))`,
  `CREATE TABLE IF NOT EXISTS debriefs (day text PRIMARY KEY, obs_count int, created double precision, data jsonb)`,
  `CREATE TABLE IF NOT EXISTS login_attempts (ip text, ts double precision)`,
  `CREATE TABLE IF NOT EXISTS day_facts (day text PRIMARY KEY, data jsonb, updated double precision)`,
];

// Tests and demo videos run against an in-process Postgres (PGlite) so they never touch the real Neon DB.
// Only used when WATCHER_LOCAL_DB=pglite; production always uses Neon.
function pglite(): Sql {
  const g = globalThis as unknown as { __watcherPg?: Promise<{ query: (t: string, v: unknown[]) => Promise<{ rows: Row[] }> }> };
  return async (strings, ...values) => {
    g.__watcherPg ??= (async () => {
      const { PGlite } = await import("@electric-sql/pglite");
      const db = new PGlite();
      for (const s of SCHEMA) await db.query(s);
      return db;
    })();
    const db = await g.__watcherPg;
    const text = strings.reduce((a, s, i) => a + (i ? `$${i}` : "") + s, "");
    return (await db.query(text, values)).rows;
  };
}

export const sql: Sql = process.env.WATCHER_LOCAL_DB === "pglite"
  ? pglite()
  : (neon(process.env.DATABASE_URL!) as unknown as Sql);
