import { test, expect } from "@playwright/test";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { resolve, join } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

const demo = "http://127.0.0.1:8001/ui/";
test("seven beats preserve AIS gaps, layers, countdown and approval/export", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(demo);
  await expect(page.locator("#countdown")).toHaveText("01:13:31");
  await expect(page.locator("#beat-buttons button")).toHaveCount(7);
  await page.locator("#beat-buttons button").nth(0).click();
  await expect(page.locator("#vessel-layer .vessel-symbol")).toHaveCount(1);
  await expect(page.locator("#approve")).toBeDisabled();
  await page.locator("#beat-buttons button").nth(1).click();
  await expect(page.locator("#vessel-layer .vessel-symbol")).toHaveCount(0);
  await expect(page.locator("#contact-source")).toHaveText("AIS gap");
  await page.locator("#beat-buttons button").nth(2).click();
  await expect(page.locator("#radar-layer .radar-symbol")).toHaveCount(1);
  await page.locator("#layer-radar").uncheck();
  await expect(page.locator("#radar-layer")).toBeHidden();
  await page.locator("#layer-radar").check();
  await page.locator("#beat-buttons button").nth(3).click();
  await expect(page.locator("#vessel-layer .vessel-symbol")).toHaveCount(1);
  await page.locator("#beat-buttons button").nth(4).click();
  const before = await page.locator("#map").getAttribute("viewBox");
  await page.locator("#zoom-in").click();
  expect(await page.locator("#map").getAttribute("viewBox")).not.toBe(before);
  await page.locator("#beat-buttons button").nth(5).click();
  await expect(page.locator("#countdown")).toHaveText("01:13:30");
  await page.locator("#beat-buttons button").nth(6).click();
  await page.locator("#approve").click();
  await expect(page.locator("#confirm-approve")).toBeDisabled();
  await page.locator("#confirm-review").check();
  await page.locator("#confirm-approve").click();
  await expect(page.locator("#evidence-dialog")).toBeVisible();
  await expect(page.locator("#evidence-content")).toContainText(
    "Simulated operator approval",
  );
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-evidence").click();
  const download = await downloadPromise;
  const record = await readFile(await download.path(), "utf8");
  const decision = await page.evaluate(
    (html) =>
      JSON.parse(
        new DOMParser().parseFromString(html, "text/html").querySelector("pre")
          .textContent,
      ),
    record,
  );
  expect(decision.label).toBe("simulated");
  expect(decision.asset).toContain("aircraft");
  expect(record).toContain("No operational action was sent.");
  await page
    .locator("#evidence-dialog")
    .getByText("Back to chart", { exact: true })
    .click();
  await page.locator("#restart").click();
  await expect(page.locator("#approval-status")).toContainText(
    "Operator approval required",
  );
  await page.locator("#replay-speed").selectOption("120");
  await page.locator("#play").click();
  await expect(page.locator("#elapsed")).not.toHaveText("T + 00:00:00");
  await page.locator("#play").click();
  expect(errors).toEqual([]);
});

test("replay reuses SVG and response nodes during playback", async ({
  page,
}) => {
  await page.goto(demo);
  await expect(page.locator("#countdown")).toHaveText("01:13:31");
  await page.evaluate(() => {
    window.originalNodes = [
      document.querySelector("#vessel-layer .vessel-symbol"),
      document.querySelector(".response-row"),
      document.querySelector("#land path"),
    ];
  });
  await page.locator("#play").click();
  await expect(page.locator("#countdown")).not.toHaveText("01:13:31");
  expect(
    await page.evaluate(() =>
      window.originalNodes.every((node) => node.isConnected),
    ),
  ).toBe(true);
});

test("live dashboard loads received observations, filters and selects without predictions", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:8081/");
  await expect(page.locator("#metric-vessels")).toHaveText("2");
  await expect(page.locator("#feed-label")).toBeVisible();
  await expect(page.locator(".vessel-row")).toHaveCount(2);
  await page.locator("#search").fill("999000001");
  await expect(page.locator(".vessel-row")).toHaveCount(1);
  await page.locator(".vessel-row").click();
  await expect(page.locator("#selected-name")).toHaveText("SYNTHETIC TEST");
  await expect(page.locator("#selected-source")).toHaveText("Simulated");
  await expect(page.locator("#selected-speed")).toHaveText("0.0 kn");
  await page.locator("#center-selected").click();
  await page.locator("#fit-world").click();
  await page.locator("#show-ports").check();
  await page.locator("#data-access").click();
  await expect(page.locator("#api-url")).toHaveValue(
    "http://127.0.0.1:8081/api/v1/vessels",
  );
  await page.locator("#close-data").click();
  await page.locator("#clear-selection").click();
  await expect(page.locator("#selection")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("exported Space evidence runs self-contained with escaped local notes", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", (route) => route.abort());
  const bundle = await readFile("ui/evidence/assets/evidence.js", "utf8");
  const styles = await readFile("ui/evidence/assets/evidence.css", "utf8");
  const html = (
    await readFile("ui/evidence/contacts/contact-0001.html", "utf8")
  )
    .replace(/<script[^>]*src="[^"]*"[^>]*><\/script>/, () => "")
    .replace(
      /<link[^>]*rel="stylesheet"[^>]*>/,
      () => `<style>${styles}</style>`,
    )
    .replace("</body>", () => `<script>${bundle}</script></body>`);
  await page.setContent(html);
  await expect(page.locator("form[data-review]")).toBeVisible();
  await page
    .locator('textarea[name="note"]')
    .fill("<img src=x onerror=alert(1)> Reviewed uncertainty");
  await page.locator('input[name="caveats"]').check();
  await page.getByRole("button", { name: "Record local review" }).click();
  await expect(page.locator("[data-review-status]")).toContainText(
    "<img src=x onerror=alert(1)> Reviewed uncertainty",
  );
  expect(await page.locator("[data-review-status] img").count()).toBe(0);
  await page.setContent(html);
  await expect(page.locator("[data-review-status]")).toHaveText("");
  expect(errors).toEqual([]);
});

test("recorder produces a self-contained Svelte map with escaped broadcast names", async ({
  page,
}) => {
  const directory = await mkdtemp(join(tmpdir(), "argus-recorder-browser-"));
  const python = resolve(".venv/bin/python");
  try {
    const seed = spawnSync(
      python,
      [
        "-c",
        `
from datetime import datetime, timezone
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
folder = Path("2026-10-09")
folder.mkdir()
pq.write_table(pa.Table.from_pylist([{
    "recv_utc": datetime.now(timezone.utc), "msg_type": "PositionReport",
    "mmsi": 999000003, "ship_name": "</script><img src=x onerror=alert(1)>",
    "lat": 53.0, "lon": -6.0, "sog": 1.0, "cog": 90.0
}]), folder / "fixture.parquet")
`,
      ],
      { cwd: directory, encoding: "utf8" },
    );
    expect(seed.status, seed.stderr).toBe(0);
    const exported = spawnSync(
      python,
      [resolve("recorder/map.py"), directory],
      { cwd: directory, encoding: "utf8" },
    );
    expect(exported.status, exported.stderr).toBe(0);
    await page.route("**/*", (route) => route.abort());
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setContent(await readFile(join(directory, "map.html"), "utf8"));
    await expect(page.locator(".vessel-row")).toHaveCount(1);
    await page.locator(".vessel-row").click();
    await expect(page.locator(".selection")).toContainText(
      "</script><img src=x onerror=alert(1)>",
    );
    await expect(page.locator(".selection img")).toHaveCount(0);
    await page
      .getByRole("button", { name: "Center on recorded position" })
      .click();
    await page.getByRole("searchbox").fill("missing vessel");
    await expect(page.locator(".vessel-row")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
