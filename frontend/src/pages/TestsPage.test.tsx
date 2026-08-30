import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchTests } from "../lib/api";
import { TestsPage } from "./TestsPage";

vi.mock("../lib/api");

const fetchTestsMock = vi.mocked(fetchTests);

function renderPage() {
  render(
    <MemoryRouter>
      <TestsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  fetchTestsMock.mockReset();
});

describe("TestsPage", () => {
  it("lists every test with a link naming the test id", async () => {
    fetchTestsMock.mockResolvedValue([
      { test_id: "1234", student_count: 27, marks_available: 20 },
      { test_id: "5678", student_count: 3, marks_available: 10 },
    ]);
    renderPage();
    expect(await screen.findByRole("link", { name: "Test 1234" })).toHaveAttribute(
      "href",
      "/tests/1234",
    );
    expect(screen.getByRole("link", { name: "Test 5678" })).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
  });

  it("shows an empty state with a path back to the upload page", async () => {
    fetchTestsMock.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText("No tests have been uploaded yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Upload exam results" }),
    ).toHaveAttribute("href", "/");
  });

  it("raises an alert with a retry path when the list cannot be loaded", async () => {
    fetchTestsMock
      .mockRejectedValueOnce(new Error("backend down"))
      .mockResolvedValueOnce([
        { test_id: "1234", student_count: 27, marks_available: 20 },
      ]);
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load the test list",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Test 1234" })).toBeInTheDocument();
  });
});
