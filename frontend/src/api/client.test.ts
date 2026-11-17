import { describe, expect, it } from "vitest";

import { mockApi } from "@/test/utils";

import { ApiError, api, setCsrfToken } from "./client";

describe("api client", () => {
  it("sends the CSRF token on changes but not on reads", async () => {
    const { calls } = mockApi({
      "GET /thing": { body: { ok: true } },
      "POST /thing": { body: { ok: true } },
    });
    setCsrfToken("token-123");
    await api.get("/thing");
    await api.post("/thing", { a: 1 });
    expect(calls[0]?.headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1]?.headers["X-CSRF-Token"]).toBe("token-123");
    expect(calls[1]?.headers["Content-Type"]).toBe("application/json");
    expect(calls[1]?.body).toEqual({ a: 1 });
    setCsrfToken(null);
  });

  it("turns the error envelope into an ApiError", async () => {
    mockApi({
      "POST /admin/users": {
        status: 422,
        body: {
          error: {
            code: "validation_failed",
            message: "The request contains invalid values.",
            details: [{ field: "username", message: "Already in use." }],
            request_id: "req-42",
          },
        },
      },
    });
    const error = await api.post("/admin/users", {}).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe("validation_failed");
    expect(apiError.fieldErrors("username")).toEqual(["Already in use."]);
    expect(apiError.fieldErrors("password")).toEqual([]);
    expect(apiError.requestId).toBe("req-42");
  });

  it("reads Retry-After for rate limits", async () => {
    mockApi({
      "POST /auth/login": {
        status: 429,
        headers: { "retry-after": "37" },
        body: { error: { code: "rate_limited", message: "Too many attempts.", details: [] } },
      },
    });
    const error = (await api.post("/auth/login", {}).catch((caught: unknown) => caught)) as ApiError;
    expect(error.retryAfter).toBe(37);
  });

  it("reports an unreachable service as a network error", async () => {
    const { fetchMock } = mockApi({});
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const error = (await api.get("/anything").catch((caught: unknown) => caught)) as ApiError;
    expect(error.isNetwork).toBe(true);
    expect(error.code).toBe("network_error");
  });

  it("handles empty 204 responses and skips empty query values", async () => {
    const { calls } = mockApi({ "DELETE /auth/sessions/x": { status: 204 }, "GET /list": { body: [] } });
    await expect(api.delete("/auth/sessions/x")).resolves.toBeNull();
    await api.get("/list", { search: "", cursor: null, limit: 5 });
    expect(calls[1]?.url.search).toBe("?limit=5");
  });
});
