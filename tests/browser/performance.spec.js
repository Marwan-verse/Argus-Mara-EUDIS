import { test, expect } from "@playwright/test";

test("paused and hidden replay does no animation work, then resumes and stops at the end", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.frames = 0;
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) =>
      raf((time) => {
        window.frames++;
        callback(time);
      });
  });
  await page.goto("http://127.0.0.1:8001/ui/");
  await expect(page.locator("#countdown")).toHaveText("01:13:31");
  await expect(page.locator("#evidence-content")).toBeEmpty();
  await page.waitForTimeout(150);
  await page.evaluate(() => {
    window.frames = 0;
  });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.frames)).toBe(0);
  await page.locator("#play").click();
  await expect(page.locator("#countdown")).not.toHaveText("01:13:31");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const hiddenTime = await page.locator("#elapsed").innerText();
  await page.waitForTimeout(100);
  await page.evaluate(() => {
    window.frames = 0;
  });
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.frames)).toBe(0);
  await expect(page.locator("#elapsed")).toHaveText(hiddenTime);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator("#elapsed")).not.toHaveText(hiddenTime);
  await page.locator("#play").click();
  await page
    .locator("#timeline")
    .fill(
      String(Number(await page.locator("#timeline").getAttribute("max")) - 1),
    );
  await page.locator("#replay-speed").selectOption("120");
  await page.locator("#play").click();
  await expect(page.locator("#play")).toHaveText("▶ Play");
});

async function largeFeed(page) {
  const received = new Date().toISOString();
  const vessels = Array.from({ length: 5000 }, (_, index) => ({
    mmsi: String(999000000 + index),
    name: `TEST ${String(index).padStart(4, "0")}`,
    label: "simulated",
    lat: 53,
    lon: -6,
    received_utc: received,
    sog_kn: 0,
    cog_deg: 0,
  }));
  const snapshot = {
    schema_version: 1,
    stream_id: "large-test",
    sequence: 1,
    vessels,
    feed: {
      label: "simulated",
      status: "receiving",
      last_received_utc: received,
    },
  };
  await page.route("**/api/v1/vessels", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.addInitScript(() => {
    window.work = { sorts: 0, draws: 0 };
    const sort = Array.prototype.sort;
    Array.prototype.sort = function (...args) {
      if (this.length >= 5000) window.work.sorts++;
      return sort.apply(this, args);
    };
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      if (this.canvas.id === "map") window.work.draws++;
      return clear.apply(this, args);
    };
    window.EventSource = class {
      listeners = new Map();
      constructor() {
        window.events = this;
      }
      addEventListener(type, callback) {
        this.listeners.set(type, callback);
      }
      close() {}
    };
    window.emit = (type, payload) =>
      window.events.listeners.get(type)({ data: JSON.stringify(payload) });
  });
  await page.goto("http://127.0.0.1:8081/");
  await expect(page.locator("#metric-vessels")).toHaveText("5,000");
  return snapshot;
}

test("5,000-contact directory pages and searches without sorting or repainting on heartbeats", async ({
  page,
}) => {
  const snapshot = await largeFeed(page);
  await expect(page.locator(".vessel-row")).toHaveCount(90);
  await expect(page.locator("#map-empty")).toBeHidden();
  await page.locator("#show-more").click();
  await expect(page.locator(".vessel-row")).toHaveCount(180);
  await page.locator("#search").fill("  test 4999  ");
  await expect(page.locator(".vessel-row")).toHaveCount(1);
  await page.locator(".vessel-row").click();
  await expect(page.locator("#selected-name")).toHaveText("TEST 4999");
  await page.waitForTimeout(200);
  await page.evaluate(() => {
    window.row = document.querySelector(".vessel-row");
    window.work = { sorts: 0, draws: 0 };
    window.emit("heartbeat", {
      stream_id: "large-test",
      feed: { status: "no_key" },
    });
  });
  await expect(page.locator("#metric-feed")).toHaveText("Waiting for feed");
  await page.waitForTimeout(1100);
  expect(await page.evaluate(() => window.work)).toEqual({
    sorts: 0,
    draws: 0,
  });
  expect(await page.evaluate(() => window.row.isConnected)).toBe(true);
  await page.evaluate(
    (vessel) =>
      window.emit("update", {
        stream_id: "large-test",
        sequence: 2,
        upserts: [{ ...vessel, name: "RENAMED CONTACT", sog_kn: 1 }],
      }),
    snapshot.vessels.at(-1),
  );
  await expect(page.locator("#selected-name")).toHaveText("RENAMED CONTACT");
  await expect(page.locator("#selected-speed")).toHaveText("1.0 kn");
  await expect(page.locator("#no-results")).toBeVisible();
  await page.locator("#search").fill("renamed");
  await expect(page.locator(".vessel-row")).toHaveCount(1);
  await page.evaluate(() =>
    window.emit("update", {
      stream_id: "large-test",
      sequence: 3,
      removals: ["999004999"],
    }),
  );
  await expect(page.locator("#selection")).toHaveCount(0);
  await expect(page.locator("#no-results")).toBeVisible();
  await page.evaluate(() =>
    window.emit("snapshot", {
      schema_version: 1,
      stream_id: "restarted-test",
      sequence: 0,
      vessels: [],
      feed: { status: "waiting" },
    }),
  );
  await expect(page.locator("#metric-vessels")).toHaveText("0");
  await expect(page.locator("#map-empty")).toBeVisible();
});

test("real map markers still age without repeated idle map redraws", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.fixtureNow = Date.now();
    Date.now = () => window.fixtureNow;
  });
  const snapshot = await largeFeed(page);
  const now = await page.evaluate(() => window.fixtureNow);
  await page.evaluate(
    (vessel) => {
      window.markerColors = [];
      const fill = CanvasRenderingContext2D.prototype.fill;
      CanvasRenderingContext2D.prototype.fill = function (...args) {
        if (this.canvas.id === "map") window.markerColors.push(this.fillStyle);
        return fill.apply(this, args);
      };
      window.emit("snapshot", {
        schema_version: 1,
        stream_id: "age-test",
        sequence: 0,
        vessels: [vessel],
        feed: { status: "receiving" },
      });
    },
    {
      ...snapshot.vessels[0],
      label: "real",
      received_utc: new Date(now - 1800000 + 60000).toISOString(),
    },
  );
  await expect(page.locator("#metric-vessels")).toHaveText("1");
  await expect
    .poll(() => page.evaluate(() => window.markerColors))
    .toContain("#2556c8");
  await page.evaluate(() => {
    window.work.draws = 0;
    window.markerColors = [];
  });
  await page.waitForTimeout(1100);
  expect(await page.evaluate(() => window.work.draws)).toBe(0);
  await page.evaluate(() => {
    window.fixtureNow += 60001;
  });
  await expect
    .poll(() => page.evaluate(() => window.markerColors))
    .toContain("#8199a9");
  expect(await page.evaluate(() => window.work.draws)).toBe(1);
});

test("live directory remains usable on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:8081/");
  await expect(page.locator(".vessel-row")).toHaveCount(2);
  await page.locator("#search").fill("999000001");
  await page.locator(".vessel-row").click();
  await expect(page.locator("#selected-name")).toBeVisible();
  await page.locator("#center-selected").click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/live-mobile.png" });
});
