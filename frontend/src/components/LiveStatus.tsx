type Props = {
  announcement: string;
  lastRefreshed: Date | null;
  stale: boolean;
};

// The visible timestamp updates on every poll and deliberately sits outside
// any live region; the hidden status region only ever receives text when new
// results arrive, so screen readers hear arrivals and nothing else. A failing
// connection turns the dot amber and labels the data stale.
export function LiveStatus({ announcement, lastRefreshed, stale }: Props) {
  return (
    <div className="live-status">
      <span className={stale ? "live-dot stale" : "live-dot"} aria-hidden="true" />
      <span>
        {lastRefreshed
          ? `Last refreshed ${lastRefreshed.toLocaleTimeString()}`
          : "Waiting for first refresh"}
        {stale ? " (connection lost, retrying)" : ""}
      </span>
      <span className="visually-hidden" role="status">
        {announcement}
      </span>
    </div>
  );
}
