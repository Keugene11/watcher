import { test, type Browser, type Page } from "@playwright/test";
import { execFileSync } from "child_process";
import { mkdirSync, mkdtempSync, renameSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join, resolve } from "path";
import { INGEST_TOKEN } from "../playwright.config";

const ROOT = resolve(__dirname, "..", "..");
const PY = join(ROOT, ".venv", "Scripts", "python.exe");
const OUT = join(ROOT, "docs", "videos");
const FFMPEG = process.env.FFMPEG ?? "ffmpeg";

async function caption(page: Page, text: string, ms = 2600) {
  await page.evaluate((t) => {
    let el = document.getElementById("__cap");
    if (!el) {
      el = document.createElement("div");
      el.id = "__cap";
      el.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;max-width:88vw;" +
        "background:rgba(15,15,20,.88);color:#fff;font:600 17px/1.4 system-ui,Segoe UI,sans-serif;padding:10px 18px;" +
        "border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.3);text-align:center;pointer-events:none";
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  await page.waitForTimeout(ms);
}

async function record(browser: Browser, name: string, size: { width: number; height: number }, fn: (p: Page) => Promise<void>, mobile = false) {
  const dir = mkdtempSync(join(tmpdir(), "watcher-vid-"));
  const ctx = await browser.newContext({ viewport: size, recordVideo: { dir, size }, ...(mobile ? { isMobile: true, hasTouch: true, deviceScaleFactor: 2 } : {}) });
  const page = await ctx.newPage();
  await fn(page);
  await ctx.close();
  const webm = await page.video()!.path();
  mkdirSync(OUT, { recursive: true });
  const mp4 = join(OUT, `${name}.mp4`);
  execFileSync(FFMPEG, ["-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "slow", "-movflags", "+faststart", mp4]);
  rmSync(dir, { recursive: true, force: true });
}

const CANNED_DEBRIEF = {
  debrief: {
    headline: "Solid coding morning, then the afternoon leaked into HN, X and two CS2 matches.",
    fixes: [
      { title: "Run one test, not the suite", detail: "You re-ran the full pnpm test 4 times for one failing test around 03:30. Use vitest -t." },
      { title: "Template the LinkedIn DMs", detail: "12 minutes on one DM. One template per company type, personalize line 1." },
      { title: "Cap browsing at 10 minutes", detail: "35 minutes of HN and X with nothing opened or saved." },
    ],
    hurt: ["Context switching between terminal and X every few minutes after 02:00.", "Rolled to 0 gold at 3-2 in TFT on a weak board."],
    good: ["A 1h40m deep-work block on the watcher test suite with focus 8-9."],
  },
  obs_count: 26, created: Date.now() / 1000,
};

test("local dashboard tour", async ({ browser }) => {
  await record(browser, "1-local-dashboard", { width: 1280, height: 800 }, async (page) => {
    await page.goto("http://127.0.0.1:8799");
    await caption(page, "watcher · local dashboard (127.0.0.1 only) · demo data, not real activity", 3000);
    await caption(page, "Live status, today's active time, avg focus and deep work with a streak");
    await page.locator("#week").scrollIntoViewIfNeeded();
    await caption(page, "This week: faint = time at the screen, green = deep work (focus 7+)");
    await page.getByRole("button", { name: "Pause" }).click();
    await caption(page, "Pause: nothing is logged or screenshotted until you resume", 2200);
    await page.getByRole("button", { name: "Resume" }).click();
    await page.getByRole("button", { name: "Check now" }).click();
    await caption(page, "Check now: the latest screenshots go to Claude Haiku right away", 2000);
    await page.getByText("Shipping the watcher test suite").waitFor({ timeout: 20_000 });
    await page.getByText("Shipping the watcher test suite").scrollIntoViewIfNeeded();
    await caption(page, "New check lands in the feed with a concrete tip; screenshots are deleted after", 3200);
  });
});

test("cloud dashboard tour", async ({ browser }) => {
  const dir = mkdtempSync(join(tmpdir(), "watcher-vid-push-"));
  execFileSync(PY, ["tests/seed_demo.py", "--push", "http://localhost:3999", INGEST_TOKEN], { cwd: ROOT, env: { ...process.env, WATCHER_DATA_DIR: dir } });
  await record(browser, "2-cloud-dashboard", { width: 1280, height: 800 }, async (page) => {
    await page.route("**/api/debrief**", (r) => r.fulfill({ json: CANNED_DEBRIEF }));
    await page.goto("http://localhost:3999");
    await caption(page, "watcher · cloud dashboard · demo data synced through /api/ingest", 3000);
    await caption(page, "Daily feedback: the fixes that buy back the most time tomorrow", 3000);
    await page.locator(".trow:not([disabled])").first().click();
    await page.getByText("Where your time went").scrollIntoViewIfNeeded();
    await caption(page, "Where your time went, per app and per site (private windows show as (private))", 3000);
    await page.locator(".tiplist").scrollIntoViewIfNeeded();
    await caption(page, "Tips ranked by impact; reworded repeats are filtered on the PC", 2600);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.locator(".wk").nth(4).click();
    await caption(page, "Last 7 days: click a day to see its checks, tips and feedback", 3000);
  });
});

test("mobile + daily report", async ({ browser }) => {
  await record(browser, "3-mobile-and-report", { width: 390, height: 844 }, async (page) => {
    await page.route("**/api/debrief**", (r) => r.fulfill({ json: CANNED_DEBRIEF }));
    await page.goto("http://localhost:3999");
    await caption(page, "Same dashboard at 390px", 2400);
    await page.mouse.wheel(0, 900);
    await page.waitForTimeout(1200);
    await page.mouse.wheel(0, 1400);
    await caption(page, "Tips and timeline stack on phones; no sideways scroll", 2400);
    const report = process.env.DEMO_REPORT;
    if (report) {
      await page.goto("file:///" + report.split(String.fromCharCode(92)).join("/"));
      await caption(page, "report.bat: daily report written by Haiku 5.5 from the fake week", 3000);
      await page.mouse.wheel(0, 900);
      await caption(page, "Deep-work blocks, where focus leaked, and a 7-day trend", 2800);
      await page.mouse.wheel(0, 1100);
      await caption(page, "Repeated tips are grouped (\"said 3x\") so habits stand out", 2800);
    }
  }, true);
});
