import { expect, test } from "@playwright/test";

import { SAMPLE_XML, documentFor, uploadXml } from "./helpers";

// The journey the brief describes: a grading machine's document goes in
// through the dashboard, and the numbers come back out.
test.describe("import and read", () => {
  test("uploads the sample file and reports what was imported", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Upload exam results/);

    // The button stays out of reach until there is something to send.
    await expect(page.getByRole("button", { name: "Upload" })).toBeDisabled();

    await uploadXml(page, "sample_results.xml", SAMPLE_XML);
    await expect(page.getByRole("button", { name: "Upload" })).toBeEnabled();
    await page.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("status")).toHaveText("Imported 100 records.");
    // 100 records, 81 students: the rest are re-scans the server merged.
    await expect(page.getByRole("alert")).toBeEmpty();
  });

  test("lists the imported test with its student count", async ({ page }) => {
    await page.goto("/tests");
    const row = page.getByRole("row").filter({ hasText: "Test 9863" });
    await expect(row).toBeVisible();
    await expect(row.getByRole("rowheader")).toHaveText("Test 9863");
    await expect(row.getByRole("cell").nth(0)).toHaveText("81");
    await expect(row.getByRole("cell").nth(1)).toHaveText("20");
  });

  test("shows the statistics the brief works through", async ({ page }) => {
    await page.goto("/tests");
    await page.getByRole("link", { name: "Test 9863" }).click();

    await expect(page).toHaveURL(/\/tests\/9863$/);
    await expect(page).toHaveTitle(/Test 9863/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Test 9863");

    const stats = page.getByRole("definition");
    // KPI order: the three headline numbers first, then the detail tier.
    await expect(stats).toHaveText([
      "81", // students
      "50.8%", // mean
      "50%", // median
      "30%", // min
      "75%", // max
      "45%", // p25
      "55%", // p75
      "9.92%", // stddev
    ]);
  });

  test("draws the ten-bin distribution", async ({ page }) => {
    await page.goto("/tests/9863");

    const bars = page.getByRole("list", { name: /Score distribution/ }).getByRole("listitem");
    await expect(bars).toHaveCount(10);
    // Counts computed from the sample file independently of the backend.
    await expect(bars.nth(3)).toHaveAccessibleName("30 to under 40 percent: 6 students");
    await expect(bars.nth(4)).toHaveAccessibleName("40 to under 50 percent: 28 students");
    await expect(bars.nth(6)).toHaveAccessibleName("60 to under 70 percent: 14 students");
    await expect(bars.nth(9)).toHaveAccessibleName("90 to 100 percent: 0 students");
  });

  test("a re-scan raises a mark and never lowers one", async ({ page }) => {
    // Three documents for one student: the middle one is the high-water mark
    // and the last one must not undo it.
    await uploadXml(page, "first.xml", documentFor("e2e-rescan", "1001", 20, 8), {
      navigate: true,
    });
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toHaveText("Imported 1 record.");

    await uploadXml(page, "second.xml", documentFor("e2e-rescan", "1001", 20, 17));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toHaveText("Imported 1 record.");

    await uploadXml(page, "third.xml", documentFor("e2e-rescan", "1001", 20, 3));
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toHaveText("Imported 1 record.");

    await page.goto("/tests/e2e-rescan");
    const stats = page.getByRole("definition");
    await expect(stats.first()).toHaveText("1"); // one student
    await expect(stats.nth(1)).toHaveText("85%"); // 17 of 20, not 3 or 8
  });

  test("re-importing an unchanged document changes nothing", async ({ page }) => {
    await page.goto("/tests/9863");
    const before = await page.getByRole("definition").allTextContents();

    await uploadXml(page, "sample_results.xml", SAMPLE_XML, { navigate: true });
    await page.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("status")).toHaveText("Imported 100 records.");

    await page.goto("/tests/9863");
    await expect(page.getByRole("definition")).toHaveText(before);
  });
});
