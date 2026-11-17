/**
 * Minimal typed client for the OmniOSINT API.
 *
 * - Same-origin requests only; the session lives in an HttpOnly cookie.
 * - State-changing requests carry the CSRF token returned by login and /auth/me.
 * - Every failure becomes an ApiError built from the backend's error envelope.
 */

export const API_BASE = "/api/v1";

export interface ApiErrorDetail {
  field?: string | null;
  in?: string;
  message?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly hint: string | null;
  readonly requestId: string | null;
  readonly retryAfter: number | null;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    details?: ApiErrorDetail[];
    hint?: string | null;
    requestId?: string | null;
    retryAfter?: number | null;
  }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? [];
    this.hint = init.hint ?? null;
    this.requestId = init.requestId ?? null;
    this.retryAfter = init.retryAfter ?? null;
  }

  /** Messages for one form field, from the envelope's details. */
  fieldErrors(field: string): string[] {
    return this.details
      .filter((detail) => detail.field === field && typeof detail.message === "string")
      .map((detail) => detail.message as string);
  }

  get isAuthentication(): boolean {
    return this.status === 401;
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token ?? null;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `${url}?${encoded}` : url;
}

function parseJson(text: string): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function errorFromResponse(response: Response, body: unknown): ApiError {
  const envelope =
    body && typeof body === "object" && "error" in body
      ? (body as { error: Record<string, unknown> }).error
      : null;
  const retryHeader = response.headers.get("retry-after");
  return new ApiError({
    status: response.status,
    code: typeof envelope?.code === "string" ? envelope.code : `http_${response.status}`,
    message:
      typeof envelope?.message === "string"
        ? envelope.message
        : `The request failed (HTTP ${response.status}).`,
    details: Array.isArray(envelope?.details) ? (envelope.details as ApiErrorDetail[]) : [],
    hint: typeof envelope?.hint === "string" ? envelope.hint : null,
    requestId:
      (typeof envelope?.request_id === "string" ? envelope.request_id : null) ??
      response.headers.get("x-request-id"),
    retryAfter: retryHeader ? Number.parseInt(retryHeader, 10) || null : null,
  });
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "The OmniOSINT service could not be reached.",
    });
  }

  const body = parseJson(await response.text());
  if (!response.ok) throw errorFromResponse(response, body);
  return body as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    apiRequest<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  delete: <T = void>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
};
