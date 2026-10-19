const {
  chromium,
} = require("playwright");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  await page.goto("http://127.0.0.1:8000/ui/");
  await page.locator("#timeline").waitFor();
  for (const [t, name] of [
    [0, "normal"],
    [2400, "gap"],
    [5400, "alert"],
  ]) {
    await page.locator("#timeline").fill(String(t));
    await page.locator("#timeline").dispatchEvent("input");
    await page.screenshot({ path: `public/${name}.png` });
  }
  console.log((await page.locator("button").allTextContents()).join(" | "));
  await page
    .getByRole("button", { name: "Review evidence", exact: true })
    .click();
  await page.screenshot({ path: "public/review.png" });
  await browser.close();
})();
