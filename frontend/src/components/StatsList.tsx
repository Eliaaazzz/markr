import { Aggregate } from "../lib/api";

function pct(value: number): string {
  return `${value}%`;
}

type Props = {
  aggregate: Aggregate;
  testId: string;
};

// A definition list keeps every number programmatically tied to its label,
// so a screen reader hears "Mean" and "65%" as one item. Visually it is a
// KPI row: the three numbers a projector audience needs first read large,
// the distribution detail sits in a quieter second tier.
export function StatsList({ aggregate, testId }: Props) {
  const items = [
    { label: "Students", value: String(aggregate.count), tier: "primary" },
    { label: "Mean", value: pct(aggregate.mean), tier: "primary" },
    { label: "Median", value: pct(aggregate.p50), tier: "primary" },
    { label: "Minimum", value: pct(aggregate.min), tier: "secondary" },
    { label: "Maximum", value: pct(aggregate.max), tier: "secondary" },
    { label: "25th percentile", value: pct(aggregate.p25), tier: "secondary" },
    { label: "75th percentile", value: pct(aggregate.p75), tier: "secondary" },
    { label: "Std deviation", value: pct(aggregate.stddev), tier: "secondary" },
  ];
  return (
    <dl className="stats" aria-label={`Summary statistics for test ${testId}`}>
      {items.map(({ label, value, tier }) => (
        <div key={label} data-tier={tier}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
