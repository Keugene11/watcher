import { NextResponse, type NextRequest } from "next/server";
import { isAuthed } from "@/lib/auth";

const OPEN = ["/login", "/api/login", "/api/ingest"];

export function proxy(req: NextRequest) {
  const p = req.nextUrl.pathname;
  if (!OPEN.includes(p) && !isAuthed(req)) {
    if (p.startsWith("/api/")) return NextResponse.json({ error: "unauthorized" }, { status: 401 });
    return NextResponse.redirect(new URL("/login", req.url));
  }
  const res = NextResponse.next();
  res.headers.set("X-Frame-Options", "DENY");
  res.headers.set("X-Content-Type-Options", "nosniff");
  res.headers.set("Referrer-Policy", "no-referrer");
  res.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  if (p.startsWith("/api/")) res.headers.set("Cache-Control", "no-store");
  return res;
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };
