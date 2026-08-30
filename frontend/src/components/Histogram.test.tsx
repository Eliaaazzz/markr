import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Histogram as HistogramData } from "../lib/api";
import { Histogram } from "./Histogram";

function tenBins(counts: number[]): HistogramData {
  return {
    bins: counts.map((count, i) => ({
      lower_pct: i * 10,
      upper_pct: (i + 1) * 10,
      count,
    })),
    total: counts.reduce((a, b) => a + b, 0),
  };
}

describe("Histogram", () => {
  it("names the chart after the test", () => {
    render(<Histogram histogram={tenBins([0, 0, 0, 6, 28, 28, 14, 5, 0, 0])} testId="9863" />);
    expect(
      screen.getByRole("list", { name: "Score distribution for test 9863" }),
    ).toBeInTheDocument();
  });

  it("renders one self-describing bar per bin, all ten present", () => {
    render(<Histogram histogram={tenBins([0, 0, 0, 6, 28, 28, 14, 5, 0, 0])} testId="9863" />);
    const bars = screen.getAllByRole("listitem");
    expect(bars).toHaveLength(10);
    expect(
      screen.getByRole("listitem", { name: "30 to under 40 percent: 6 students" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("listitem", { name: "0 to under 10 percent: 0 students" }),
    ).toBeInTheDocument();
  });

  it("keeps the last bin closed at 100 and uses the singular correctly", () => {
    render(<Histogram histogram={tenBins([0, 0, 0, 0, 0, 0, 0, 0, 0, 1])} testId="7" />);
    expect(
      screen.getByRole("listitem", { name: "90 to 100 percent: 1 student" }),
    ).toBeInTheDocument();
  });
});
