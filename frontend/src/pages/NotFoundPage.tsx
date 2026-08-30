import { Link } from "react-router-dom";

import { usePageTitle } from "../lib/usePageTitle";

export function NotFoundPage() {
  usePageTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <p className="page-intro-note">There is nothing at this address.</p>
      <p className="page-actions">
        <Link to="/">Upload exam results</Link>
      </p>
      <p className="page-actions">
        <Link to="/tests">All tests</Link>
      </p>
    </>
  );
}
