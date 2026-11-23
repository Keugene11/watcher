import base from "./playwright.config";
import { defineConfig, type PlaywrightTestConfig } from "@playwright/test";

type Servers = NonNullable<Extract<PlaywrightTestConfig["webServer"], unknown[]>>;

// Records the demo videos in docs/videos with the same throwaway servers as the e2e tests (fake data only).
export default defineConfig({ ...base, testDir: "./demo", timeout: 180_000,
  webServer: (base.webServer as Servers).filter((_, i) => i !== 1 && i !== 3) });
