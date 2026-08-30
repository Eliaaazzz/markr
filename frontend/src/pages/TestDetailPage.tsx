import { Link, useParams } from "react-router-dom";

import { Histogram } from "../components/Histogram";
import { LiveStatus } from "../components/LiveStatus";
import { StatsList } from "../components/StatsList";
import { usePageTitle } from "../lib/usePageTitle";
import { useLiveTestData } from "../lib/useLiveTestData";

export function TestDetailPage() {
  const { testId = "" } = useParams();
  const live = useLiveTestData(testId);
  usePageTitle(`Test ${testId}`);

  return (
    <>
      <div className="page-head">
        <h1>Test {testId}</h1>
        {(live.phase === "ready" || live.phase === "missing") && (
          <LiveStatus
            announcement={live.announcement}
            lastRefreshed={live.lastRefreshed}
            stale={live.stale}
          />
        )}
      </div>
      {live.phase === "loading" && <p className="loading-note">Loading results.</p>}
      {live.phase === "error" && (
        <>
          <p className="alert-box" role="alert" data-populated="true">
            Could not load results for this test. The connection will keep
            retrying on its own.
          </p>
          <p className="page-actions">
            <button type="button" onClick={live.retry}>
              Retry now
            </button>
          </p>
          <p className="page-actions">
            <Link to="/tests" className="back-link">
              Back to all tests
            </Link>
          </p>
        </>
      )}
      {live.phase === "missing" && (
        <div className="empty-state">
          <p>
            There is no test with this id. Nothing has been imported for it,
            or the id in the address is wrong.
          </p>
          <p className="page-actions">
            <Link to="/tests" className="back-link">
              Back to all tests
            </Link>
          </p>
        </div>
      )}
      {live.phase === "ready" && live.aggregate && live.histogram && (
        <>
          <StatsList aggregate={live.aggregate} testId={testId} />
          <Histogram histogram={live.histogram} testId={testId} />
          <p className="page-actions">
            <Link to="/tests" className="back-link">
              Back to all tests
            </Link>
          </p>
        </>
      )}
    </>
  );
}
