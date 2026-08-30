import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatsList } from "./StatsList";

const AGGREGATE = {
  mean: 65,
  stddev: 0,
  min: 65,
  max: 65,
  p25: 65,
  p50: 65,
  p75: 65,
  count: 1,
};

describe("StatsList", () => {
  it("shows all eight statistics, each tied to its label", () => {
    render(<StatsList aggregate={AGGREGATE} testId="1234" />);
    expect(screen.getAllByRole("term")).toHaveLength(8);
    expect(screen.getAllByRole("definition")).toHaveLength(8);
    const mean = screen.getByText("Mean").closest("div");
    expect(mean).toHaveTextContent("65%");
    const students = screen.getByText("Students").closest("div");
    expect(students).toHaveTextContent("1");
  });

  it("presents percentages with their unit", () => {
    render(<StatsList aggregate={{ ...AGGREGATE, mean: 50.8 }} testId="9863" />);
    expect(screen.getByText("50.8%")).toBeInTheDocument();
  });
});
