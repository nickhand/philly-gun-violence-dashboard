import { expect, test } from "@playwright/test";
import { mockDashboardApi } from "./support/mockApi";

test("loads Montserrat from the application without third-party font requests", async ({
  page,
}) => {
  const fontRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      request.resourceType() === "font" ||
      url.pathname.endsWith(".woff2") ||
      url.hostname === "fonts.googleapis.com" ||
      url.hostname === "fonts.gstatic.com"
    ) {
      fontRequests.push(url.href);
    }
  });

  await mockDashboardApi(page);
  await page.goto("./");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const montserratLoaded = await page.evaluate(async () => {
    await document.fonts.ready;
    return document.fonts.check("400 32px Montserrat");
  });

  expect(montserratLoaded).toBe(true);
  expect(fontRequests.some((url) =>
    url.endsWith("/fonts/montserrat/montserrat-latin.woff2"),
  )).toBe(true);
  for (const fontUrl of fontRequests) {
    expect(new URL(fontUrl).origin).toBe(new URL(page.url()).origin);
  }
});
