import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join, resolve } from "path";

// Everything here runs against throwaway data: PGlite in-process Postgres for the cloud app, temp SQLite dirs
// seeded with fake activity for the local dashboard. Nothing touches Neon or data/watcher.db.
const ROOT = resolve(__dirname, "..");
const PY = join(ROOT, ".venv", "Scripts", "python.exe");
export const INGEST_TOKEN = "test-ingest-token-0123456789";
export const PASSWORD = "correct horse";
const demoDir = process.env.E2E_DEMO_DIR ?? mkdtempSync(join(tmpdir(), "watcher-e2e-demo-"));
const emptyDir = process.env.E2E_EMPTY_DIR ?? mkdtempSync(join(tmpdir(), "watcher-e2e-empty-"));
process.env.E2E_DEMO_DIR = demoDir;
process.env.E2E_EMPTY_DIR = emptyDir;

const nextEnv = (extra: Record<string, string>) => ({
  WATCHER_LOCAL_DB: "pglite", INGEST_TOKEN, AUTH_SECRET: "test-auth-secret-0123456789abcdef",
  DASHBOARD_PASSWORD: PASSWORD, ANTHROPIC_API_KEY: "", DATABASE_URL: "", ...extra,
});
const pyEnv = (dir: string, port: number) => ({
  WATCHER_DATA_DIR: dir, WATCHER_DASH_PORT: String(port), WATCHER_CLOUD_URL: "", INGEST_TOKEN: "", ANTHROPIC_API_KEY: "",
});

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { ...devices["Desktop Chrome"], trace: "off" },
  webServer: [
    { command: "pnpm exec next dev -p 3999", port: 3999, timeout: 180_000, reuseExistingServer: false,
      env: nextEnv({ NEXT_DIST_DIR: ".next-e2e-public" }) },
    { command: "pnpm exec next dev -p 3998", port: 3998, timeout: 180_000, reuseExistingServer: false,
      env: nextEnv({ NEXT_DIST_DIR: ".next-e2e-login", REQUIRE_LOGIN: "1" }) },
    { command: `"${PY}" tests/seed_demo.py --serve`, cwd: ROOT, port: 8799,
      timeout: 60_000, reuseExistingServer: false, env: pyEnv(demoDir, 8799) },
    { command: `"${PY}" dashboard.py --no-open`, cwd: ROOT, port: 8798, timeout: 60_000, reuseExistingServer: false,
      env: pyEnv(emptyDir, 8798) },
  ],
});
