import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { importResults } from "../lib/api";
import { UploadPage } from "./UploadPage";

vi.mock("../lib/api");

const importResultsMock = vi.mocked(importResults);

function renderPage() {
  render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>,
  );
}

function xmlFile(): File {
  return new File(["<mcq-test-results/>"], "results.xml", { type: "text/xml" });
}

beforeEach(() => {
  importResultsMock.mockReset();
});

describe("UploadPage", () => {
  it("labels the file picker and disables upload until a file is chosen", async () => {
    renderPage();
    const button = screen.getByRole("button", { name: "Upload" });
    expect(button).toBeDisabled();
    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    expect(button).toBeEnabled();
  });

  it("reports the imported count as a polite status", async () => {
    importResultsMock.mockResolvedValue(100);
    renderPage();
    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("Imported 100 records.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Imported 100 records.");
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("uses the singular for a single record", async () => {
    importResultsMock.mockResolvedValue(1);
    renderPage();
    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("Imported 1 record.")).toBeInTheDocument();
  });

  it("keeps a rejected document in the alert channel only", async () => {
    importResultsMock.mockRejectedValue(new Error("record 2: missing student-number"));
    renderPage();
    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText("record 2: missing student-number")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("record 2: missing student-number");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("hands the raw file to the importer, not a decoded string", async () => {
    importResultsMock.mockResolvedValue(1);
    renderPage();
    const file = xmlFile();
    await userEvent.upload(screen.getByLabelText("Results XML file"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    await screen.findByText("Imported 1 record.");
    // The File object itself: re-encoding legacy XML behind its declaration
    // is exactly what this page must never do.
    expect(importResultsMock).toHaveBeenCalledWith(file, expect.any(AbortSignal));
  });

  it("refuses a file over the 10 MB limit without a network call", async () => {
    renderPage();
    const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "big.xml", {
      type: "text/xml",
    });
    await userEvent.upload(screen.getByLabelText("Results XML file"), big);
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(await screen.findByText(/larger than the 10 MB limit/)).toBeInTheDocument();
    expect(importResultsMock).not.toHaveBeenCalled();
  });

  it("clears earlier feedback when a different file is chosen", async () => {
    importResultsMock.mockResolvedValue(100);
    renderPage();
    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    await screen.findByText("Imported 100 records.");

    await userEvent.upload(screen.getByLabelText("Results XML file"), xmlFile());
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("links to the tests page", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "View all tests" })).toBeInTheDocument();
  });
});
