import { DragEvent, FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import { importResults } from "../lib/api";
import { usePageTitle } from "../lib/usePageTitle";

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const UPLOAD_TIMEOUT_MS = 30_000;

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPage() {
  usePageTitle("Upload exam results");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [problem, setProblem] = useState("");
  const [dragOver, setDragOver] = useState(false);

  function takeFile(next: File | null) {
    setFile(next);
    // A newly chosen file makes the previous outcome irrelevant.
    setStatus("");
    setProblem("");
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragOver(false);
    const dropped = event.dataTransfer.files?.[0] ?? null;
    if (dropped) {
      takeFile(dropped);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) {
      return;
    }
    setStatus("");
    setProblem("");
    // The server caps documents at 10 MB; saying so here spares a slow
    // upload that was always going to be rejected.
    if (file.size > MAX_UPLOAD_BYTES) {
      setProblem("This file is larger than the 10 MB limit.");
      return;
    }
    setBusy(true);
    const aborter = new AbortController();
    const timeout = window.setTimeout(() => aborter.abort(), UPLOAD_TIMEOUT_MS);
    try {
      // The File goes to the server as raw bytes; reading it into a string
      // here would re-encode legacy documents behind their XML declaration.
      const imported = await importResults(file, aborter.signal);
      setStatus(`Imported ${imported} ${imported === 1 ? "record" : "records"}.`);
      setFile(null);
    } catch (error) {
      if (aborter.signal.aborted) {
        setProblem("The upload timed out. Check the connection and try again.");
      } else {
        setProblem(error instanceof Error ? error.message : "Upload failed.");
      }
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
    }
  }

  return (
    <>
      <hgroup className="page-intro">
        <h1>Upload exam results</h1>
        <p>Send a grading machine&apos;s XML document to the results store.</p>
      </hgroup>
      <form className="upload-form" onSubmit={handleSubmit} aria-busy={busy}>
        {/* The label is the whole dropzone; the input keeps its concise
            accessible name via aria-label so the extra affordance copy
            never leaks into it. */}
        <label
          htmlFor="results-file"
          className={dragOver ? "dropzone drag-over" : "dropzone"}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <svg
            className="dropzone-icon"
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 16V4m0 0 4.2 4.2M12 4 7.8 8.2" />
            <path d="M4 15.5v2.1A2.4 2.4 0 0 0 6.4 20h11.2a2.4 2.4 0 0 0 2.4-2.4v-2.1" />
          </svg>
          <span className="dropzone-title">Results XML file</span>
          <span className="dropzone-hint">
            Drag and drop the document here, or{" "}
            <span className="dropzone-browse">browse</span>
          </span>
        </label>
        <input
          id="results-file"
          className="visually-hidden"
          type="file"
          aria-label="Results XML file"
          accept=".xml,text/xml,application/xml"
          onChange={(event) => takeFile(event.target.files?.[0] ?? null)}
        />
        {file && (
          <p className="file-chip">
            <svg
              className="file-chip-icon"
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
              <path d="M13 3v6h6" />
            </svg>
            <span className="file-chip-name">{file.name}</span>
            <span className="file-chip-size">{formatSize(file.size)}</span>
          </p>
        )}
        <button type="submit" disabled={!file || busy}>
          {busy && <span className="button-spinner" aria-hidden="true" />}
          {busy ? "Uploading" : "Upload"}
        </button>
      </form>
      {/* Success and failure live in separate regions so a screen reader
          hears a rejection announced as a problem, never as routine status. */}
      <p className="status-box" role="status" data-populated={status !== ""}>
        {status}
      </p>
      <p className="alert-box" role="alert" data-populated={problem !== ""}>
        {problem}
      </p>
      <p className="page-actions">
        <Link to="/tests">View all tests</Link>
      </p>
    </>
  );
}
