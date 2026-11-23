import { createHmac, timingSafeEqual } from "crypto";

export const COOKIE = "w_auth";
const SESSION_DAYS = 30;

// REQUIRE_LOGIN=1 puts the dashboard behind DASHBOARD_PASSWORD (recommended for any real deployment).
export const loginRequired = () => process.env.REQUIRE_LOGIN === "1";

function sign(v: string) {
  const secret = process.env.AUTH_SECRET;
  if (!secret || secret.length < 16) throw new Error("AUTH_SECRET missing or too short");
  return createHmac("sha256", secret).update(v).digest("hex");
}

function safeEq(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Expiring session token: "<exp>.<hmac(exp)>". Rotate AUTH_SECRET to log everyone out. */
export function sessionToken(now = Date.now()) {
  const exp = Math.floor(now / 1000) + SESSION_DAYS * 86400;
  return `${exp}.${sign(`watcher-session-v2.${exp}`)}`;
}

export function validSession(token: string | undefined, now = Date.now()) {
  if (!token) return false;
  const [exp, mac] = token.split(".");
  if (!exp || !mac || !/^\d+$/.test(exp) || Number(exp) * 1000 < now) return false;
  try { return safeEq(mac, sign(`watcher-session-v2.${exp}`)); } catch { return false; }
}

export function checkPassword(pw: string) {
  const real = process.env.DASHBOARD_PASSWORD;
  if (!real) return false;
  return safeEq(sign(`pw.${pw}`), sign(`pw.${real}`));
}

export function cookieFrom(req: Request) {
  const m = (req.headers.get("cookie") ?? "").match(new RegExp(`(?:^|;\\s*)${COOKIE}=([^;]+)`));
  return m?.[1];
}

/** True when the request may read/control the dashboard. */
export function isAuthed(req: Request) {
  return !loginRequired() || validSession(cookieFrom(req));
}

export function isIngestAuthed(req: Request) {
  const token = process.env.INGEST_TOKEN;
  if (!token || token.length < 16) return false; // fail closed: an unset env must not accept "Bearer undefined"
  return safeEq(req.headers.get("authorization") ?? "", `Bearer ${token}`);
}

/** Blocks cross-site requests (CSRF) to state-changing routes. Browsers send Sec-Fetch-Site / Origin. */
export function sameOrigin(req: Request) {
  const site = req.headers.get("sec-fetch-site");
  if (site) return site === "same-origin" || site === "none";
  const origin = req.headers.get("origin");
  if (!origin) return true; // non-browser client (curl); CSRF needs a browser
  try { return new URL(origin).host === req.headers.get("host"); } catch { return false; }
}
