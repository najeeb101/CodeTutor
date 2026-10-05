// The one way the UI calls the API (docs/api.md). In the browser, paths go through the /api
// rewrite in next.config.ts; in a server component there is no "current page", so the full
// API address is needed.
import { API_URL } from "./config";

export class ApiError extends Error {
  constructor(
    public readonly status: number, // 0 = the API could not be reached
    public readonly detail: string,
    public readonly retryAfterS: number | null = null,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

const UNREACHABLE = "Can't reach the API. Is it running? (make api)";

interface ApiOptions {
  method?: "GET" | "POST" | "PUT";
  userId?: number; // sent as X-User-Id (dev login, not secure)
  body?: unknown; // sent as JSON
}

export async function apiFetch<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.userId !== undefined) headers["X-User-Id"] = String(options.userId);
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const base = typeof window === "undefined" ? API_URL : "";

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store", // problems change with a sync, results change while grading
    });
  } catch {
    throw new ApiError(0, UNREACHABLE);
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorDetail(response), retryAfter(response));
  }
  return (await response.json()) as T;
}

// FastAPI answers {"detail": "text"}, or {"detail": [{"msg": ...}, ...]} for a request that
// doesn't match its model. Anything else (e.g. the proxy's HTML page when the API is down)
// gets a short message.
async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = body.detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map((error) => String(error?.msg)).join("; ");
    }
  } catch {
    // not JSON
  }
  return response.status >= 500 ? `${UNREACHABLE} (HTTP ${response.status})` : `HTTP ${response.status}`;
}

function retryAfter(response: Response): number | null {
  const seconds = Number(response.headers.get("Retry-After"));
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}
