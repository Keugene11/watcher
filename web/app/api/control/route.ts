import { NextResponse } from "next/server";
import { sameOrigin } from "@/lib/auth";
import { sql } from "@/lib/db";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ error: "cross-site request blocked" }, { status: 403 });
  const { action } = await req.json().catch(() => ({ action: null }));
  if (action === "pause") await sql`UPDATE control SET pause = true WHERE id = 1`;
  else if (action === "resume") await sql`UPDATE control SET pause = false WHERE id = 1`;
  else if (action === "check") await sql`UPDATE control SET force_check = true WHERE id = 1`;
  else return NextResponse.json({ error: "bad action" }, { status: 400 });
  return NextResponse.json({ ok: true });
}
