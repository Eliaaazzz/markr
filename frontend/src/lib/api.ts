// Typed client for the backend API. Everything goes through the /api prefix,
// which nginx (in the container) and the vite dev server both proxy.

export type TestSummary = {
  test_id: string;
  student_count: number;
  marks_available: number;
};

export type Aggregate = {
  mean: number;
  stddev: number;
  min: number;
  max: number;
  p25: number;
  p50: number;
  p75: number;
  count: number;
};

export type HistogramBin = {
  lower_pct: number;
  upper_pct: number;
  count: number;
};

export type Histogram = {
  bins: HistogramBin[];
  total: number;
};

export class NotFoundError extends Error {
  constructor(path: string) {
    super(`Not found: ${path}`);
    this.name = "NotFoundError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, { signal });
  if (response.status === 404) {
    throw new NotFoundError(path);
  }
  if (!response.ok) {
    throw new Error(`GET ${path} failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchTests(): Promise<TestSummary[]> {
  const body = await getJson<{ tests: TestSummary[] }>("/tests");
  return body.tests;
}

export function fetchAggregate(
  testId: string,
  signal?: AbortSignal,
): Promise<Aggregate> {
  return getJson<Aggregate>(
    `/results/${encodeURIComponent(testId)}/aggregate`,
    signal,
  );
}

export function fetchHistogram(
  testId: string,
  signal?: AbortSignal,
): Promise<Histogram> {
  return getJson<Histogram>(
    `/results/${encodeURIComponent(testId)}/histogram`,
    signal,
  );
}

export type Dashboard = {
  aggregate: Aggregate;
  histogram: Histogram;
};

// One request instead of two, so the count and the distribution always come
// from the same database read and a poll racing an import cannot show a
// student total that disagrees with its own histogram.
export function fetchDashboard(
  testId: string,
  signal?: AbortSignal,
): Promise<Dashboard> {
  return getJson<Dashboard>(
    `/results/${encodeURIComponent(testId)}/dashboard`,
    signal,
  );
}

export async function importResults(
  xml: File | Blob | string,
  signal?: AbortSignal,
): Promise<number> {
  // A File is sent as its raw bytes. Reading it into a string first would
  // decode and re-encode it, silently corrupting any legacy document whose
  // XML declaration disagrees with UTF-8.
  const response = await fetch("/api/import", {
    method: "POST",
    headers: { "Content-Type": "text/xml+markr" },
    body: xml,
    signal,
  });
  const body = (await response.json().catch(() => null)) as
    | { imported?: number; error?: string }
    | null;
  if (!response.ok) {
    throw new Error(body?.error ?? `Import failed with status ${response.status}`);
  }
  if (typeof body?.imported !== "number") {
    // A 2xx without the count is a contract breach; success must never be
    // fabricated from a malformed response.
    throw new Error("Unexpected response from the server.");
  }
  return body.imported;
}
