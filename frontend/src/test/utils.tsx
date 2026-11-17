import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { vi } from "vitest";

import { setCsrfToken } from "@/api/client";
import { createQueryClient } from "@/app/queryClient";
import { routes } from "@/app/router";

export interface MockRequest {
  method: string;
  path: string;
  url: URL;
  body: unknown;
  headers: Record<string, string>;
}

export interface MockResponse {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}

type Handler = MockResponse | ((request: MockRequest) => MockResponse);

/** Replace fetch with a router of "METHOD /path" handlers (paths without /api/v1). */
export function mockApi(handlers: Record<string, Handler>) {
  const calls: MockRequest[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://127.0.0.1:8765");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const request: MockRequest = {
      method,
      path,
      url,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers: { ...((init?.headers as Record<string, string> | undefined) ?? {}) },
    };
    calls.push(request);
    const handler = handlers[`${method} ${path}`];
    if (handler === undefined) {
      return new Response(
        JSON.stringify({ error: { code: "not_found", message: `No mock for ${method} ${path}`, details: [] } }),
        { status: 404, headers: { "content-type": "application/json" } },
      );
    }
    const result = typeof handler === "function" ? handler(request) : handler;
    const status = result.status ?? 200;
    return new Response(status === 204 || result.body === undefined ? null : JSON.stringify(result.body), {
      status,
      headers: { "content-type": "application/json", ...result.headers },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

/** Render the real application routes at `path`. */
export function renderApp(path: string) {
  setCsrfToken(null);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = createQueryClient();
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, client, ...view };
}

export function errorBody(code: string, message: string, details: unknown[] = []) {
  return { error: { code, message, details, request_id: "req-test-1" } };
}
