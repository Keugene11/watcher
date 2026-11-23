import { expect, test, type APIRequestContext } from "@playwright/test";
import { execFileSync } from "child_process";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join, resolve } from "path";
import { INGEST_TOKEN, PASSWORD } from "../playwright.config";

const PUB = "http://localhost:3999";
const LOGIN = "http://localhost:3998";
const ROOT = resolve(__dirname, "..", "..");
const PY = join(ROOT, ".venv", "Scripts", "python.exe");
const auth = { Authorization: `Bearer ${INGEST_TOKEN}` };

async function ingest(request: APIRequestContext, body: unknown, base = PUB) {
  return request.post(`${base}/api/ingest`, { headers: auth, data: body });
}

test.describe.serial("cloud dashboard (public mode)", () => {
  test("empty state before the PC has ever synced", async ({ page }) => {
    await page.goto(PUB);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("No data yet");
    await expect(page.getByText("PC offline")).toBeVisible();
    await expect(page.getByRole("button", { name: /Check now/ })).toBeDisabled();
  });

  test("ingest rejects missing / wrong tokens", async ({ request }) => {
    expect((await request.post(`${PUB}/api/ingest`, { data: {} })).status()).toBe(401);
    expect((await request.post(`${PUB}/api/ingest`, { headers: { Authorization: "Bearer nope" }, data: {} })).status()).toBe(401);
    expect((await request.post(`${PUB}/api/ingest`, { headers: { Authorization: "Bearer undefined" }, data: {} })).status()).toBe(401);
    expect((await ingest(request, "not json")).status()).toBe(400);
  });

  test("seed a fake week through the real ingest path", async () => {
    const dir = mkdtempSync(join(tmpdir(), "watcher-e2e-push-"));
    execFileSync(PY, ["tests/seed_demo.py", "--push", PUB, INGEST_TOKEN], { cwd: ROOT, env: { ...process.env, WATCHER_DATA_DIR: dir } });
  });

  test("feed renders: status, days, debrief empty state, tips, timeline, time spent", async ({ page }) => {
    await page.goto(PUB);
    await expect(page.locator(".pill")).toHaveText(/Watching/);
    await expect(page.getByRole("navigation", { name: "Days" }).getByRole("button")).toHaveCount(7);
    await expect(page.getByText("Where your time went")).toBeVisible();
    await expect(page.getByText(/No feedback yet|Claude is reading/)).toBeVisible();
    await expect(page.locator(".tiplist li").first()).toBeVisible();
    await expect(page.locator(".ev").first()).toBeVisible();
    await expect(page.locator(".wk")).toHaveCount(7);
    await expect(page.locator(".dayhead .stats")).toContainText("deep work");
    await page.locator(".trow:not([disabled])").first().click();
    await expect(page.locator(".tsites").first()).toBeVisible();
  });

  test("switching days", async ({ page }) => {
    await page.goto(PUB);
    await page.getByRole("button", { name: /Yesterday/ }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Yesterday/);
  });

  test("window titles and summaries are rendered as text (no XSS)", async ({ page, request }) => {
    const evil = `<img src=x onerror="window.__xss=1">`;
    const day = (await (await request.get(`${PUB}/api/state`)).json()).status.day;
    const r = await ingest(request, {
      status: { heartbeat: Date.now() / 1000, day, app: `evil${evil}.exe`, title: evil, idle: false, paused: false, next_check: 100, pending: 0, checking: false, model: "m" },
      observations: [{ id: 999999, day, ts_start: Date.now() / 1000 - 100, ts_end: Date.now() / 1000, category: "coding", focus: 5,
        summary: `<script>window.__xss=2</script>${evil}`, tips: [{ tip: evil, why: evil, impact: "high" }], input_tokens: 1, output_tokens: 1 }],
      apps: { [`x${evil}`]: 60 }, details: [[`x${evil}`, evil, evil, 60]],
    });
    expect(r.ok()).toBeTruthy();
    await page.goto(PUB);
    await expect(page.locator(".now")).toContainText("<img src=x");
    await expect(page.getByText(`<script>window.__xss=2</script>`, { exact: false }).first()).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
    expect(await page.locator("img[src=x]").count()).toBe(0);
  });

  test("ingest clamps junk input", async ({ request }) => {
    const day = (await (await request.get(`${PUB}/api/state`)).json()).status.day;
    const r = await ingest(request, {
      status: { heartbeat: Date.now() / 1000, day, app: "a".repeat(5000), title: "t".repeat(5000), idle: false, paused: false },
      observations: [{ id: 999998, day, category: "hacking", focus: 99, summary: 42, tips: "nope" }],
    });
    expect(r.ok()).toBeTruthy();
    const s = await (await request.get(`${PUB}/api/state`)).json();
    expect(s.status.app.length).toBe(120);
    expect(s.status.title.length).toBe(200);
    const o = s.observations.find((x: { id: string | number }) => Number(x.id) === 999998);
    expect(o.category).toBe("other");
    expect(o.focus).toBe(10);
  });

  test("pause and resume round-trip through the PC sync", async ({ page, request }) => {
    const day = (await (await request.get(`${PUB}/api/state`)).json()).status.day;
    const pc = (paused: boolean) => ingest(request, { status: { heartbeat: Date.now() / 1000, day, app: "Code.exe", title: "x", idle: false, paused, next_check: 300, pending: 1, checking: false, model: "claude-haiku-5-5" } });
    await pc(false);
    await page.goto(PUB);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: /Sending/ })).toBeVisible();
    const cmd = await (await pc(false)).json(); // the PC's next sync picks up the command exactly once
    expect(cmd.pause).toBe(true);
    expect((await (await pc(true)).json()).pause).toBeNull();
    await page.reload();
    await expect(page.locator(".pill")).toHaveText(/Paused/);
    await page.getByRole("button", { name: "Resume" }).click();
    expect((await (await pc(true)).json()).pause).toBe(false);
    await pc(false);
    await page.reload();
    await expect(page.locator(".pill")).toHaveText(/Watching/);
  });

  test("check now", async ({ page, request }) => {
    await page.goto(PUB);
    await page.getByRole("button", { name: /Check now/ }).click();
    await expect(page.getByRole("button", { name: /Checking/ })).toBeVisible();
    const day = (await (await request.get(`${PUB}/api/state`)).json()).status.day;
    const cmd = await (await ingest(request, { status: { heartbeat: Date.now() / 1000, day, app: "Code.exe", title: "x", paused: false, checking: true } })).json();
    expect(cmd.force_check).toBe(true);
  });

  test("control endpoint blocks cross-site requests (CSRF)", async ({ request }) => {
    const r = await request.post(`${PUB}/api/control`, { headers: { Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, data: { action: "pause" } });
    expect(r.status()).toBe(403);
    const r2 = await request.post(`${PUB}/api/control`, { headers: { Origin: "https://evil.example" }, data: { action: "pause" } });
    expect(r2.status()).toBe(403);
    expect((await request.post(`${PUB}/api/control`, { data: { action: "rm -rf" } })).status()).toBe(400);
  });

  test("security headers", async ({ request }) => {
    const r = await request.get(PUB);
    expect(r.headers()["x-frame-options"]).toBe("DENY");
    expect(r.headers()["x-powered-by"]).toBeUndefined();
  });

  test("390px mobile: no sideways scroll", async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await ctx.newPage();
    await page.goto(PUB);
    await expect(page.locator(".pill")).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(over).toBeLessThanOrEqual(0);
    await ctx.close();
  });
});

test.describe.serial("cloud dashboard with REQUIRE_LOGIN=1", () => {
  test("everything but ingest/login is gated", async ({ page, request }) => {
    expect((await request.get(`${LOGIN}/api/state`)).status()).toBe(401);
    expect((await request.post(`${LOGIN}/api/control`, { data: { action: "pause" } })).status()).toBe(401);
    expect((await request.get(`${LOGIN}/api/debrief?day=2026-11-11`)).status()).toBe(401);
    await page.goto(LOGIN);
    await expect(page).toHaveURL(/\/login$/);
  });

  test("forged / expired cookies are rejected", async ({ request }) => {
    for (const c of ["w_auth=1", "w_auth=9999999999.deadbeef", "w_auth=1.abc"]) {
      expect((await request.get(`${LOGIN}/api/state`, { headers: { Cookie: c } })).status()).toBe(401);
    }
  });

  test("wrong then right password", async ({ page }) => {
    await page.goto(`${LOGIN}/login`);
    await page.getByLabel("Password").fill("nope");
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page.locator(".err")).toHaveText("Wrong password");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page).toHaveURL(`${LOGIN}/`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const cookie = (await page.context().cookies()).find((c) => c.name === "w_auth")!;
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.sameSite).toBe("Lax");
  });

  test("brute force is rate limited", async ({ request }) => {
    let last = 0;
    for (let i = 0; i < 11; i++) last = (await request.post(`${LOGIN}/api/login`, { data: { password: `guess${i}` } })).status();
    expect(last).toBe(429);
  });
});
