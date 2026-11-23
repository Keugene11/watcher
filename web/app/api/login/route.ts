import { NextResponse } from "next/server";
import { COOKIE, checkPassword, loginRequired, sameOrigin, sessionToken } from "@/lib/auth";
import { sql } from "@/lib/db";

const WINDOW = 15 * 60, MAX_FAILS = 10;
let ready = false;

export async function POST(req: Request) {
  if (!loginRequired()) return NextResponse.json({ ok: true });
  if (!sameOrigin(req)) return NextResponse.json({ error: "cross-site request blocked" }, { status: 403 });
  if (!ready) { await sql`CREATE TABLE IF NOT EXISTS login_attempts (ip text, ts double precision)`; ready = true; }
  const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
  const now = Date.now() / 1000;
  const [{ n }] = await sql`SELECT count(*)::int AS n FROM login_attempts WHERE ip = ${ip} AND ts > ${now - WINDOW}`;
  if (n >= MAX_FAILS) return NextResponse.json({ error: "Too many attempts. Try again in 15 minutes." }, { status: 429 });

  const { password } = await req.json().catch(() => ({ password: "" }));
  if (!checkPassword(String(password ?? ""))) {
    await sql`INSERT INTO login_attempts (ip, ts) VALUES (${ip}, ${now})`;
    await sql`DELETE FROM login_attempts WHERE ts < ${now - 86400}`;
    await new Promise((r) => setTimeout(r, 800));
    return NextResponse.json({ error: "Wrong password" }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE, sessionToken(), { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 30 });
  return res;
}
