import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { TestSummary, fetchTests } from "../lib/api";
import { usePageTitle } from "../lib/usePageTitle";

export function TestsPage() {
  usePageTitle("Tests");
  const [tests, setTests] = useState<TestSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setTests(null);
    setFailed(false);
    fetchTests()
      .then((result) => {
        if (!cancelled) {
          setTests(result);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <>
      <hgroup className="page-intro">
        <h1>Tests</h1>
        <p>Every test the results store knows about, updated as imports land.</p>
      </hgroup>
      {failed && (
        <>
          <p className="alert-box" role="alert" data-populated="true">
            Could not load the test list. Check that the backend is running.
          </p>
          <p className="page-actions">
            <button type="button" onClick={() => setReloadKey((k) => k + 1)}>
              Try again
            </button>
          </p>
        </>
      )}
      {!failed && tests === null && <p>Loading the test list.</p>}
      {tests !== null && tests.length === 0 && (
        <div className="empty-state">
          <p>No tests have been uploaded yet.</p>
          <p className="page-actions">
            <Link to="/">Upload exam results</Link>
          </p>
        </div>
      )}
      {tests !== null && tests.length > 0 && (
        <div className="table-card">
          <table>
            <thead>
              <tr>
                <th scope="col">Test</th>
                <th scope="col">Students</th>
                <th scope="col">Marks available</th>
              </tr>
            </thead>
            <tbody>
            {tests.map((test) => (
              <tr key={test.test_id}>
                <th scope="row">
                  <Link to={`/tests/${encodeURIComponent(test.test_id)}`}>
                    Test {test.test_id}
                  </Link>
                </th>
                <td>{test.student_count}</td>
                <td>{test.marks_available}</td>
              </tr>
            ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
