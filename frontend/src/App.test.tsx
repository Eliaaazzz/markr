import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { fetchTests } from "./lib/api";

vi.mock("./lib/api");

describe("App", () => {
  it("shows a not-found page for unknown routes", () => {
    render(
      <MemoryRouter initialEntries={["/definitely/not/here"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All tests" })).toBeInTheDocument();
  });

  it("moves focus to the incoming heading after navigation", async () => {
    vi.mocked(fetchTests).mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("link", { name: "Tests" }));
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Tests" })).toHaveFocus(),
    );
  });

  it("titles the document per page", async () => {
    vi.mocked(fetchTests).mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/tests"]}>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => expect(document.title).toBe("Tests · Markr"));
  });
});
