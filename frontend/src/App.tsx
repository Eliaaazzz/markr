import { useEffect, useRef } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";

import { NotFoundPage } from "./pages/NotFoundPage";
import { TestDetailPage } from "./pages/TestDetailPage";
import { TestsPage } from "./pages/TestsPage";
import { UploadPage } from "./pages/UploadPage";

// Client-side navigation swaps content without a page load; moving focus to
// the incoming heading tells keyboard and screen-reader users where they
// landed. The first render is left alone so page load behaves natively.
function RouteFocus() {
  const { pathname } = useLocation();
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const heading = document.querySelector<HTMLElement>("main h1");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus();
    }
  }, [pathname]);
  return null;
}

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header>
        <nav aria-label="Primary">
          <span className="brand">
            <svg
              className="brand-mark"
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
            >
              <rect width="24" height="24" rx="6" fill="currentColor" />
              <path
                d="M6.5 17.5v-5m5.5 5v-9m5.5 9v-3"
                stroke="#fff"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
            Markr
          </span>
          <span className="nav-links">
            <NavLink to="/">Upload</NavLink>
            <NavLink to="/tests">Tests</NavLink>
          </span>
        </nav>
      </header>
      {/* tabIndex makes the skip link's fragment target reliably focusable
          across browser and screen-reader pairings. */}
      <main id="main" tabIndex={-1}>
        <RouteFocus />
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/tests" element={<TestsPage />} />
          <Route path="/tests/:testId" element={<TestDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </>
  );
}
