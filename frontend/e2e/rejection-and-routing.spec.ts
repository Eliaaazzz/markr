import { expect, test } from "@playwright/test";

import { documentFor, uploadXml } from "./helpers";

// Failure paths, and the routing and header behaviour that only exists once
// the app is served by nginx. None of this is reachable from a jsdom test.
test.describe("rejection", () => {
  test("a malformed document is reported and nothing is stored", async ({ page }) => {
    await uploadXml(page, "broken.xml", "<mcq-test-results><oops>", {
      navigate: true,
    });
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("alert")).not.toBeEmpty();
    await expect(page.getByRole("status")).toBeEmpty();

    // The rejection must be total: no partial test appears in the listing.
    await page.goto("/tests");
    await expect(page.getByRole("link", { name: /Test oops/ })).toHaveCount(0);
  });

  test("a document whose marks exceed the total names the offending record", async ({
    page,
  }) => {
    await uploadXml(page, "impossible.xml", documentFor("e2e-bad", "1001", 20, 21), {
      navigate: true,
    });
    await page.getByRole("button", { name: "Upload" }).click();

    // The server explains which record failed; the page shows that verbatim.
    await expect(page.getByRole("alert")).toContainText(/record 1/i);
    await page.goto("/tests/e2e-bad");
    await expect(page.getByText("There is no test with this id.")).toBeVisible();
  });

  test("choosing a new file clears the previous outcome", async ({ page }) => {
    await uploadXml(page, "broken.xml", "<mcq-test-results><oops>", {
      navigate: true,
    });
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("alert")).not.toBeEmpty();

    await uploadXml(page, "fine.xml", documentFor("e2e-clear", "1001", 20, 10));
    await expect(page.getByRole("alert")).toBeEmpty();
  });
});

test.describe("routing", () => {
  test("a deep link is served by the SPA fallback, not a 404", async ({ page }) => {
    // nginx try_files has to hand /tests/9863 the app shell on a cold load.
    const response = await page.goto("/tests/9863");
    expect(response?.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Test 9863");
  });

  test("an unknown test id explains itself instead of erroring", async ({ page }) => {
    await page.goto("/tests/definitely-not-a-test");
    await expect(page.getByText("There is no test with this id.")).toBeVisible();
    await page.getByRole("link", { name: "Back to all tests" }).click();
    await expect(page).toHaveURL(/\/tests$/);
  });

  test("an unknown route shows the not-found page", async ({ page }) => {
    await page.goto("/no/such/page");
    await expect(page).toHaveTitle(/Page not found/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
  });

  test("a missing bundle 404s rather than falling back to the shell", async ({
    request,
  }) => {
    // Serving index.html for a missing hashed asset would turn a bad deploy
    // into a blank page with a syntax error instead of a clear 404.
    const response = await request.get("/assets/index-doesnotexist.js");
    expect(response.status()).toBe(404);
  });

  test("the primary nav moves between the two pages", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Primary" });
    await nav.getByRole("link", { name: "Tests" }).click();
    await expect(page).toHaveURL(/\/tests$/);
    await nav.getByRole("link", { name: "Upload" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});

test.describe("edge hardening", () => {
  test("the shell carries the security headers", async ({ page }) => {
    const response = await page.goto("/");
    const headers = response?.headers() ?? {};

    expect(headers["content-security-policy"]).toContain("default-src 'self'");
    expect(headers["content-security-policy"]).toContain("frame-ancestors 'none'");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["referrer-policy"]).toBe("no-referrer");
    // nginx drops inherited add_header sets inside a location that declares
    // its own, so the /assets/ and / blocks are checked separately.
    expect(headers["cache-control"]).toContain("no-cache");
  });

  test("hashed bundles are cached immutably", async ({ page, request }) => {
    await page.goto("/");
    const src = await page.locator("script[src^='/assets/']").getAttribute("src");
    expect(src).toBeTruthy();

    const response = await request.get(src!);
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toContain("immutable");
    expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  });

  test("the api is reachable at the same origin through the proxy", async ({
    request,
  }) => {
    const response = await request.get("/api/health");
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });

  test("an oversized upload is refused at the edge", async ({ request }) => {
    // nginx client_max_body_size stops this before the backend spends time
    // parsing it; either layer answering 4xx is a pass.
    const response = await request.post("/api/import", {
      headers: { "Content-Type": "text/xml+markr" },
      data: `<mcq-test-results>${" ".repeat(11 * 1024 * 1024)}</mcq-test-results>`,
    });
    expect(response.status()).toBeGreaterThanOrEqual(400);
    expect(response.status()).toBeLessThan(500);
  });
});
