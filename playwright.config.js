import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
const python = `"${resolve(process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")}"`;
export default defineConfig({
  testDir: "./tests/browser",
  workers: 1,
  use: {
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      ...(existsSync("/usr/bin/chromium")
        ? { executablePath: "/usr/bin/chromium" }
        : {}),
    },
  },
  webServer: [
    {
      command: `${python} scripts/serve_demo.py --port 8001`,
      url: "http://127.0.0.1:8001/ui/",
      reuseExistingServer: false,
    },
    {
      command: `${python} tests/serve_live_fixture.py`,
      url: "http://127.0.0.1:8081/healthz",
      reuseExistingServer: false,
    },
    {
      command: `${python} tests/serve_admin_fixture.py`,
      url: "http://127.0.0.1:8082/healthz",
      reuseExistingServer: false,
    },
  ],
});
