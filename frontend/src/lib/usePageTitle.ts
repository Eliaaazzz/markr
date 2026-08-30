import { useEffect } from "react";

// Route changes in a single-page app never touch the document title on their
// own; setting it per page keeps tabs, history, and screen readers oriented.
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Markr`;
    return () => {
      document.title = "Markr";
    };
  }, [title]);
}
