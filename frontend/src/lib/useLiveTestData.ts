import { useCallback, useEffect, useRef, useState } from "react";

import { Aggregate, Histogram, NotFoundError, fetchDashboard } from "./api";

// The brief demands updates within 10 seconds. The cadence is measured from
// poll start and each request aborts after 6 seconds, so even a hung backend
// keeps the page inside the window; a completed poll waits out the remainder
// of the 5-second interval.
export const POLL_INTERVAL_MS = 5_000;
export const FETCH_TIMEOUT_MS = 6_000;
const MIN_GAP_MS = 1_000;
// Shaves up to this much off each wait, so a fleet of projectors started
// together drifts apart instead of polling on the same second forever.
const POLL_JITTER_MS = 500;

export type LiveTestData = {
  phase: "loading" | "ready" | "missing" | "error";
  aggregate: Aggregate | null;
  histogram: Histogram | null;
  lastRefreshed: Date | null;
  announcement: string;
  stale: boolean;
  retry: () => void;
};

type LiveState = Omit<LiveTestData, "retry">;

const INITIAL: LiveState = {
  phase: "loading",
  aggregate: null,
  histogram: null,
  lastRefreshed: null,
  announcement: "",
  stale: false,
};

/**
 * Polls one test's aggregate and histogram, tracking what a screen reader
 * should hear: nothing on first load, one announcement per actual change,
 * and an arrival announcement when data appears on a page that had none.
 * The announcement text carries a timestamp so consecutive updates always
 * differ, which is what makes a live region re-announce.
 */
export function useLiveTestData(testId: string): LiveTestData {
  const [state, setState] = useState<LiveState>(INITIAL);
  const [attempt, setAttempt] = useState(0);
  const baseline = useRef<string | null>(null);
  const lastPhase = useRef<"none" | "missing" | "ready" | "error">("none");
  const trackedTest = useRef(testId);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    // A manual retry keeps the phase memory so recovery gets announced; only
    // an actual test change starts the history over.
    if (trackedTest.current !== testId) {
      trackedTest.current = testId;
      baseline.current = null;
      lastPhase.current = "none";
    }
    setState(INITIAL);
    let cancelled = false;
    let timer: number | undefined;
    let aborter: AbortController | undefined;
    let abortTimer: number | undefined;
    let inFlight = false;

    async function tick() {
      const startedAt = Date.now();
      inFlight = true;
      aborter = new AbortController();
      abortTimer = window.setTimeout(() => aborter?.abort(), FETCH_TIMEOUT_MS);
      try {
        const { aggregate, histogram, changeToken } = await fetchDashboard(
          testId,
          aborter.signal,
        );
        if (cancelled) {
          return;
        }
        const now = new Date();
        const changed =
          baseline.current !== null && baseline.current !== changeToken;
        let announcement: string | null = null;
        if (lastPhase.current === "ready" && changed) {
          announcement =
            `Results updated at ${now.toLocaleTimeString()}: ` +
            `${aggregate.count} students, mean ${aggregate.mean}%.`;
        } else if (lastPhase.current === "missing" || lastPhase.current === "error") {
          announcement =
            `Results arrived at ${now.toLocaleTimeString()}: ` +
            `${aggregate.count} students.`;
        }
        baseline.current = changeToken;
        lastPhase.current = "ready";
        setState((prev) => ({
          phase: "ready",
          aggregate,
          histogram,
          lastRefreshed: now,
          announcement:
            announcement ??
            // Data unchanged, but a stale page just reconnected: say so, or a
            // screen-reader user never learns the numbers are current again.
            (prev.stale
              ? `Connection restored at ${now.toLocaleTimeString()}.`
              : prev.announcement),
          stale: false,
        }));
      } catch (error) {
        if (cancelled) {
          return;
        }
        if (error instanceof NotFoundError) {
          baseline.current = null;
          lastPhase.current = "missing";
          setState((prev) => ({
            ...INITIAL,
            phase: "missing",
            lastRefreshed: new Date(),
            announcement: prev.stale
              ? `Connection restored at ${new Date().toLocaleTimeString()}.`
              : prev.announcement,
          }));
        } else if (
          lastPhase.current === "ready" ||
          lastPhase.current === "missing"
        ) {
          // Keep what is on screen; a wobbly backend reads as stale data,
          // never as an empty page. "Missing" is data too: without this
          // branch an outage would keep showing a green dot next to "no
          // test with this id" while the answer may have changed.
          setState((prev) => ({
            ...prev,
            stale: true,
            announcement: prev.stale
              ? prev.announcement
              : `Connection lost at ${new Date().toLocaleTimeString()}; ` +
                "retrying automatically.",
          }));
        } else {
          lastPhase.current = "error";
          setState({ ...INITIAL, phase: "error" });
        }
      } finally {
        inFlight = false;
        window.clearTimeout(abortTimer);
        if (!cancelled) {
          const wait = Math.max(
            MIN_GAP_MS,
            POLL_INTERVAL_MS - (Date.now() - startedAt) - Math.random() * POLL_JITTER_MS,
          );
          timer = window.setTimeout(tick, wait);
        }
      }
    }

    // Server-sent events make a fresh import land immediately; the poll
    // above stays as the fallback, so losing the stream only degrades
    // freshness to the poll interval. jsdom has no EventSource, which is
    // also why this is feature-detected.
    let source: EventSource | undefined;
    if (typeof EventSource !== "undefined") {
      source = new EventSource("/api/events");
      source.onmessage = (event) => {
        if (cancelled || event.data !== testId || inFlight) {
          return;
        }
        window.clearTimeout(timer);
        void tick();
      };
    }

    tick();
    return () => {
      // Abort the in-flight request too, so navigating between tests does
      // not leave the backend finishing work nobody will render.
      cancelled = true;
      window.clearTimeout(timer);
      window.clearTimeout(abortTimer);
      aborter?.abort();
      source?.close();
    };
  }, [testId, attempt]);

  return { ...state, retry };
}
