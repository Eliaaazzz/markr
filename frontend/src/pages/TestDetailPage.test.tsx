import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Aggregate, Histogram, NotFoundError, fetchDashboard } from "../lib/api";
import { TestDetailPage } from "./TestDetailPage";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    fetchDashboard: vi.fn(),
  };
});

const dashboardMock = vi.mocked(fetchDashboard);

function resolveWith(count: number, changeToken = `version-${count}`) {
  dashboardMock.mockResolvedValue({
    aggregate: aggregate(count),
    histogram: histogram(count),
    changeToken,
  });
}

function aggregate(count: number): Aggregate {
  return {
    mean: 50.8,
    stddev: 9.92,
    min: 30,
    max: 75,
    p25: 45,
    p50: 50,
    p75: 55,
    count,
  };
}

function histogram(total: number): Histogram {
  return {
    bins: Array.from({ length: 10 }, (_, i) => ({
      lower_pct: i * 10,
      upper_pct: (i + 1) * 10,
      count: i === 5 ? total : 0,
    })),
    total,
  };
}

function renderPage(testId = "9863") {
  return render(
    <MemoryRouter initialEntries={[`/tests/${testId}`]}>
      <Routes>
        <Route path="/tests/:testId" element={<TestDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function flushPolling(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  dashboardMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TestDetailPage", () => {
  it("shows the statistics and histogram without announcing the first load", async () => {
    resolveWith(81);
    renderPage();
    await flushPolling();

    expect(screen.getByRole("heading", { name: "Test 9863" })).toBeInTheDocument();
    expect(screen.getAllByRole("term")).toHaveLength(8);
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByText(/Last refreshed/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("announces new results once, and repeats nothing while data is unchanged", async () => {
    resolveWith(81);
    renderPage();
    await flushPolling();
    expect(screen.getByRole("status")).toHaveTextContent("");

    await flushPolling(5000); // an unchanged poll stays silent
    expect(screen.getByRole("status")).toHaveTextContent("");

    resolveWith(82);
    await flushPolling(5000);
    const status = screen.getByRole("status");
    expect(status.textContent).toMatch(/^Results updated at .*: 82 students/);
    const announced = status.textContent;

    await flushPolling(5000); // still 82 students: the region must not change
    expect(screen.getByRole("status").textContent).toBe(announced);
  });

  it("announces a version change even when rounded display values stay equal", async () => {
    resolveWith(81, "version-a");
    renderPage();
    await flushPolling();
    expect(screen.getByRole("status")).toHaveTextContent("");

    resolveWith(81, "version-b");
    await flushPolling(5000);
    const status = screen.getByRole("status");
    expect(status.textContent).toMatch(/^Results updated at .*: 81 students/);
    const announced = status.textContent;

    resolveWith(81, "version-b");
    await flushPolling(5000);
    expect(screen.getByRole("status").textContent).toBe(announced);
  });

  it("keeps the visible refresh time ticking outside the live region", async () => {
    resolveWith(81);
    renderPage();
    await flushPolling();
    const first = screen.getByText(/Last refreshed/).textContent;
    await flushPolling(5000);
    const second = screen.getByText(/Last refreshed/).textContent;
    expect(second).not.toBe(first);
    expect(screen.getByRole("status")).not.toHaveTextContent(/Last refreshed/);
  });

  it("shows a clear not-found state with a way back", async () => {
    dashboardMock.mockRejectedValue(new NotFoundError("/results/404/aggregate"));
    renderPage("404");
    await flushPolling();

    expect(screen.getByText(/no test with this id/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to all tests" })).toHaveAttribute(
      "href",
      "/tests",
    );
  });

  it("shows a loud error with a retry path when the first load fails", async () => {
    dashboardMock.mockRejectedValue(new TypeError("network down"));
    renderPage();
    await flushPolling();

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load results");
    const retry = screen.getByRole("button", { name: "Retry now" });

    resolveWith(81);
    fireEvent.click(retry);
    await flushPolling();

    expect(screen.getAllByRole("term")).toHaveLength(8);
    expect(screen.getByRole("status").textContent).toMatch(/^Results arrived at/);
  });

  it("keeps stale data on screen and flags it when polling starts failing", async () => {
    resolveWith(81);
    renderPage();
    await flushPolling();
    expect(screen.getAllByRole("term")).toHaveLength(8);

    dashboardMock.mockRejectedValue(new TypeError("network down"));
    await flushPolling(5000);
    expect(screen.getAllByRole("term")).toHaveLength(8); // data survives
    expect(screen.getByText(/connection lost, retrying/)).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/^Connection lost at/);
    const lost = screen.getByRole("status").textContent;

    await flushPolling(5000); // a second failure must not re-announce
    expect(screen.getByRole("status").textContent).toBe(lost);

    resolveWith(81);
    await flushPolling(5000);
    expect(screen.queryByText(/connection lost/)).not.toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/^Connection restored at/);
  });

  it("refetches immediately when the event stream reports a change", async () => {
    // jsdom has no EventSource; a stub verifies the wiring: subscribe on
    // mount, refetch on a matching message, close on unmount.
    const instances: FakeEventSource[] = [];
    class FakeEventSource {
      static readonly CONNECTING = 0;
      onmessage: ((event: { data: string }) => void) | null = null;
      closed = false;
      constructor(public url: string) {
        instances.push(this);
      }
      close() {
        this.closed = true;
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    try {
      resolveWith(81);
      const view = renderPage();
      await flushPolling();
      expect(instances).toHaveLength(1);
      expect(instances[0].url).toBe("/api/events");

      resolveWith(82);
      instances[0].onmessage?.({ data: "9863" });
      await flushPolling();
      // The update landed without waiting out the 5-second poll.
      expect(screen.getByRole("status").textContent).toMatch(/82 students/);

      instances[0].onmessage?.({ data: "some-other-test" });
      await flushPolling();

      view.unmount();
      expect(instances.every((s) => s.closed)).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("flags an outage on a missing test instead of claiming a fresh check", async () => {
    dashboardMock.mockRejectedValue(new NotFoundError("/results/9863/dashboard"));
    renderPage();
    await flushPolling();
    expect(screen.getByText(/no test with this id/i)).toBeInTheDocument();
    expect(screen.queryByText(/connection lost/)).not.toBeInTheDocument();

    // The backend goes away entirely. The page previously kept a green dot
    // and a ticking "last refreshed" here, silently vouching for a check it
    // could not make.
    dashboardMock.mockRejectedValue(new TypeError("network down"));
    await flushPolling(5000);
    expect(screen.getByText(/no test with this id/i)).toBeInTheDocument();
    expect(screen.getByText(/connection lost, retrying/)).toBeInTheDocument();

    // Recovery to a successful 404 clears the stale flag.
    dashboardMock.mockRejectedValue(new NotFoundError("/results/9863/dashboard"));
    await flushPolling(5000);
    expect(screen.queryByText(/connection lost/)).not.toBeInTheDocument();
  });

  it("announces results that arrive on a previously empty test", async () => {
    dashboardMock.mockRejectedValue(new NotFoundError("/results/9863/aggregate"));
    renderPage();
    await flushPolling();
    expect(screen.getByText(/no test with this id/i)).toBeInTheDocument();

    resolveWith(3);
    await flushPolling(5000);
    expect(screen.getByRole("status").textContent).toMatch(
      /^Results arrived at .*: 3 students/,
    );
    expect(screen.getAllByRole("term")).toHaveLength(8);
  });
});
