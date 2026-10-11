// Local Chromium work counters, not a production speed or Core Web Vitals score.
import { chromium } from "@playwright/test";

const browser = await chromium.launch();
try {
  const replay = await browser.newPage();
  await replay.addInitScript(() => {
    window.frameCallbacks = 0;
    const raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (callback) =>
      raf((time) => {
        window.frameCallbacks++;
        callback(time);
      });
  });
  await replay.goto(process.env.DEMO_URL || "http://127.0.0.1:8002/ui/");
  await replay.locator("#countdown").waitFor();
  await replay.waitForTimeout(200);
  await replay.evaluate(() => {
    window.frameCallbacks = 0;
  });
  await replay.waitForTimeout(1000);
  const pausedFrames = await replay.evaluate(() => window.frameCallbacks);

  const live = await browser.newPage();
  const feed = { label: "simulated", status: "receiving" };
  const payload = {
    schema_version: 1,
    stream_id: "performance-fixture",
    sequence: 1,
    feed,
    vessels: Array.from({ length: 5000 }, (_, index) => ({
      mmsi: String(999000000 + index),
      name: `TEST ${String(index).padStart(4, "0")}`,
      label: "simulated",
      lat: 53 + (index % 100) / 100,
      lon: -6 + (index % 50) / 100,
      received_utc: new Date().toISOString(),
      sog_kn: 0,
      cog_deg: 0,
    })),
  };
  await live.route("**/api/v1/vessels", (route) =>
    route.fulfill({ json: payload }),
  );
  await live.addInitScript(() => {
    window.work = { sorts: 0, mapDraws: 0 };
    const sort = Array.prototype.sort;
    Array.prototype.sort = function (...args) {
      if (this.length >= 5000) window.work.sorts++;
      return sort.apply(this, args);
    };
    const clear = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      if (this.canvas.id === "map") window.work.mapDraws++;
      return clear.apply(this, args);
    };
    window.EventSource = class {
      listeners = new Map();
      constructor() {
        window.fixtureEvents = this;
      }
      addEventListener(type, listener) {
        this.listeners.set(type, listener);
      }
      close() {}
    };
  });
  await live.goto(process.env.LIVE_URL || "http://127.0.0.1:8081/");
  await live.locator(".vessel-row").first().waitFor();
  await live.waitForTimeout(300);
  await live.evaluate(() => {
    window.work = { sorts: 0, mapDraws: 0 };
  });
  for (let index = 0; index < 12; index++) {
    await live.evaluate(
      ({ feed, index }) => {
        window.fixtureEvents.listeners.get("heartbeat")({
          data: JSON.stringify({
            stream_id: "performance-fixture",
            feed: { ...feed, messages: index },
          }),
        });
      },
      { feed, index },
    );
    await live.waitForTimeout(140);
  }
  const heartbeatWork = await live.evaluate(() => window.work);
  const showMoreVisible = await live.locator("#show-more").isVisible();
  const searchStart = performance.now();
  await live.locator("#search").fill("TEST 4999");
  await live.locator('.vessel-row[data-mmsi="999004999"]').waitFor();
  console.log(
    JSON.stringify(
      {
        fixtureVessels: payload.vessels.length,
        pausedReplayCallbacksIn1s: pausedFrames,
        heartbeats: 12,
        heartbeatWork,
        showMoreVisible,
        searchRoundTripMs: Math.round(performance.now() - searchStart),
        matchingRows: await live.locator(".vessel-row").count(),
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
