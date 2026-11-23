import { neon } from "@neondatabase/serverless";
const sql = neon(process.env.DATABASE_URL);
await sql`CREATE TABLE IF NOT EXISTS status (
  id int PRIMARY KEY DEFAULT 1, heartbeat double precision, day text, app text, title text, idle boolean,
  paused boolean, next_check int, pending int, checking boolean, model text)`;
await sql`CREATE TABLE IF NOT EXISTS control (id int PRIMARY KEY DEFAULT 1, pause boolean, force_check boolean DEFAULT false)`;
await sql`INSERT INTO control (id) VALUES (1) ON CONFLICT DO NOTHING`;
await sql`CREATE TABLE IF NOT EXISTS observations (
  id bigint PRIMARY KEY, day text, ts_start double precision, ts_end double precision, category text, focus int,
  summary text, tips jsonb, input_tokens int, output_tokens int)`;
await sql`CREATE INDEX IF NOT EXISTS observations_day ON observations(day)`;
await sql`CREATE TABLE IF NOT EXISTS app_usage (day text, app text, seconds int, PRIMARY KEY (day, app))`;
console.log("migrated");
await sql`CREATE TABLE IF NOT EXISTS debriefs (day text PRIMARY KEY, obs_count int, created double precision, data jsonb)`;
console.log("debriefs ok");
