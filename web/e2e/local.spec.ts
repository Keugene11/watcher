import { expect, test } from "@playwright/test";
import { execFileSync } from "child_process";
import { join, resolve } from "path";

const DEMO = "http://127.0.0.1:8799";
const EMPTY = "http://127.0.0.1:8798";
const ROOT = resolve(__dirname, "..", "..");
const PY = join(ROOT, ".venv", "Scripts", "python.exe");

test.describe.serial("local dashboard (dashboard.py)", () => {
  test("feed renders with fake data", async ({ page }) => {
    await page.goto(DEMO);
    await expect(page.locator("#status")).toHaveText(/Watching/);
    await expect(page.locator("#feed .card").first()).toBeVisible();
    expect(await page.locator("#apps .row").count()).toBeGreaterThan(2);
    await expect(page.locator("#sTips")).not.toHaveText("–");
    await expect(page.locator("#week .wk")).toHaveCount(7);
    await expect(page.locator("#sDeep")).not.toHaveText("0m");
  });

  test("pause and resume", async ({ page }) => {
    await page.goto(DEMO);
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.locator("#status")).toHaveText(/Paused/);
    await page.getByRole("button", { name: "Resume" }).click();
    await expect(page.locator("#status")).toHaveText(/Watching/);
  });

  test("check now produces a new observation", async ({ page }) => {
    await page.goto(DEMO);
    await page.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByRole("button", { name: /Checking/ })).toBeVisible();
    await expect(page.getByText("Shipping the watcher test suite")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Check now" })).toBeEnabled();
  });

  test("hostile window title is shown as text", async ({ page }) => {
    execFileSync(PY, ["-c", "import common,time;c=common.db();c.execute('INSERT INTO activity VALUES(?,?,?,?)',(time.time(),'x.exe','<img src=x onerror=window.__xss=1>',0));c.commit()"],
      { cwd: ROOT, env: { ...process.env, WATCHER_DATA_DIR: process.env.E2E_DEMO_DIR! } });
    await page.goto(DEMO);
    await expect(page.locator("#now")).toContainText("<img src=x");
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });

  test("cross-site POST is refused", async ({ request }) => {
    expect((await request.post(`${DEMO}/api/pause`)).status()).toBe(403);
    expect((await request.post(`${DEMO}/api/pause`, { headers: { "X-Watcher": "1", Origin: "https://evil.example" } })).status()).toBe(403);
  });

  test("empty state", async ({ page }) => {
    await page.goto(EMPTY);
    await expect(page.locator("#status")).toHaveText(/Not running/);
    await expect(page.getByText("No checks yet today")).toBeVisible();
    await expect(page.getByRole("button", { name: "Check now" })).toBeDisabled();
  });

  test("390px mobile: no sideways scroll", async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await ctx.newPage();
    await page.goto(DEMO);
    await expect(page.locator("#feed .card").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
    await ctx.close();
  });
});
