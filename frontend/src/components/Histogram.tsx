import { Histogram as HistogramData } from "../lib/api";

type Props = {
  histogram: HistogramData;
  testId: string;
};

// Bars are plain list items so assistive tech can walk them; each carries its
// own accessible name and the visual spans stay decorative. One series, one
// hue; counts wear text color, never the series color, and the busiest bin's
// count is the only bold one so the peak reads at projector distance.
export function Histogram({ histogram, testId }: Props) {
  const maxCount = Math.max(...histogram.bins.map((bin) => bin.count), 1);
  return (
    <figure className="histogram-card">
      <figcaption className="histogram-title">Score distribution</figcaption>
      <ul className="histogram" aria-label={`Score distribution for test ${testId}`}>
        {histogram.bins.map((bin) => {
          const students = bin.count === 1 ? "student" : "students";
          // Bins are half-open except the last, which is closed so 100%
          // lands in it. The accessible name says which, so a score of
          // exactly 40% is never ambiguous between two bars.
          const range =
            bin.upper_pct === 100
              ? `${bin.lower_pct} to ${bin.upper_pct} percent`
              : `${bin.lower_pct} to under ${bin.upper_pct} percent`;
          const peak = bin.count === maxCount && bin.count > 0;
          return (
            <li key={bin.lower_pct} aria-label={`${range}: ${bin.count} ${students}`}>
              <span
                className={peak ? "histogram-count peak" : "histogram-count"}
                aria-hidden="true"
              >
                {bin.count}
              </span>
              <span className="histogram-track" aria-hidden="true">
                <span
                  className="histogram-bar"
                  style={{ height: `${(bin.count / maxCount) * 100}%` }}
                />
              </span>
              <span className="histogram-range" aria-hidden="true">
                {bin.lower_pct} to {bin.upper_pct}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="histogram-caption">
        Students per ten-point score range. A score on a boundary counts in the
        higher range; 100% counts in 90 to 100.
      </p>
    </figure>
  );
}
