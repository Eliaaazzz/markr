import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { Page, expect } from "@playwright/test";

const here = fileURLToPath(new URL(".", import.meta.url));

/** The fixture the brief ships with: 100 records covering 81 students. */
export const SAMPLE_XML = readFileSync(`${here}../../sample_results.xml`, "utf8");

/** A one-record document, for tests that need an id nothing else touches. */
export function documentFor(
  testId: string,
  student: string,
  available: number,
  obtained: number,
): string {
  return `<mcq-test-results>
    <mcq-test-result scanned-on="2017-12-04T12:12:10+11:00">
        <first-name>Jane</first-name>
        <last-name>Austen</last-name>
        <student-number>${student}</student-number>
        <test-id>${testId}</test-id>
        <summary-marks available="${available}" obtained="${obtained}" />
    </mcq-test-result>
</mcq-test-results>`;
}

/**
 * Put a file into the real file picker, the way a user would.
 *
 * Pass `navigate` to land on the upload page first; without it the caller is
 * assumed to be there already, mid-journey.
 */
export async function uploadXml(
  page: Page,
  name: string,
  contents: string,
  options: { navigate?: boolean } = {},
): Promise<void> {
  if (options.navigate) {
    await page.goto("/");
  }
  await page.getByLabel("Results XML file").setInputFiles({
    name,
    mimeType: "text/xml",
    buffer: Buffer.from(contents, "utf8"),
  });
  await expect(page.getByRole("button", { name: "Upload" })).toBeEnabled();
}
