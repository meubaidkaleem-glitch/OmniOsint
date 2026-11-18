import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { authState, shellHandlers, user } from "@/test/fixtures";
import { errorBody, mockApi, renderApp } from "@/test/utils";

const info = (setupRequired: boolean) => ({
  body: { service: "omniosint", version: "0.2.0", api_version: "v1", setup_required: setupRequired },
});
const signedOut = {
  "GET /auth/me": { status: 401, body: errorBody("authentication_required", "Sign in to continue.") },
};

describe("sign-in", () => {
  it("shows the server's message for wrong credentials and clears the password", async () => {
    mockApi({
      ...signedOut,
      "GET /system/info": info(false),
      "POST /auth/login": {
        status: 401,
        body: errorBody("invalid_credentials", "The username or password is incorrect, or the account is temporarily locked."),
      },
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "wrong password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/username or password is incorrect/)).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("tells the user how long to wait when throttled", async () => {
    mockApi({
      ...signedOut,
      "GET /system/info": info(false),
      "POST /auth/login": {
        status: 429,
        headers: { "retry-after": "42" },
        body: errorBody("rate_limited", "Too many attempts. Wait a moment and try again."),
      },
    });
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "whatever it is");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Try again in 42 seconds.")).toBeInTheDocument();
  });

  it("asks for a cookie session and lands on the dashboard", async () => {
    let signedIn = false;
    const { calls } = mockApi({
      ...shellHandlers(),
      "GET /auth/me": () =>
        signedIn ? { body: authState() } : { status: 401, body: errorBody("authentication_required", "Sign in.") },
      "POST /auth/login": () => {
        signedIn = true;
        return { body: { ...authState(), access_token: null, token_type: null } };
      },
      "GET /dashboard": { status: 503, body: errorBody("database_unavailable", "The database is not reachable.") },
    });
    const { router } = renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    const login = calls.find((call) => call.method === "POST" && call.path === "/auth/login");
    expect(login?.body).toMatchObject({ username: "admin", session_type: "cookie" });
  });
});

describe("first-run setup", () => {
  it("takes the token from the link and removes it from the address bar", async () => {
    window.history.replaceState(null, "", "/setup#token=abc-123-token");
    mockApi({
      ...signedOut,
      "GET /system/info": info(true),
      "GET /auth/setup-status": { body: { setup_required: true, token_file: "/home/me/token.txt" } },
    });
    renderApp("/setup");
    expect(await screen.findByLabelText("Setup token")).toHaveValue("abc-123-token");
    expect(window.location.hash).toBe("");
    expect(screen.getByText("The setup token was filled in from the link you opened.")).toBeInTheDocument();
  });

  it("checks the confirmation locally and shows field errors from the server", async () => {
    const { calls } = mockApi({
      ...signedOut,
      "GET /system/info": info(true),
      "GET /auth/setup-status": { body: { setup_required: true, token_file: "/t" } },
      "POST /auth/setup": {
        status: 422,
        body: errorBody("validation_failed", "The password does not meet the requirements.", [
          { field: "password", message: "Use at least 12 characters." },
        ]),
      },
    });
    renderApp("/setup");
    await userEvent.type(await screen.findByLabelText("Setup token"), "token-value-1234");
    await userEvent.type(screen.getByLabelText("Username"), "owner");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByRole("button", { name: "Create administrator" }));
    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    await userEvent.clear(screen.getByLabelText("Confirm password"));
    await userEvent.type(screen.getByLabelText("Confirm password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create administrator" }));
    expect(await screen.findByText("Use at least 12 characters.")).toBeInTheDocument();
  });
});

describe("administration", () => {
  it("tells users without permission that they cannot open the user list", async () => {
    mockApi(shellHandlers(authState({ permissions: [], user: { roles: ["analyst"] } })));
    renderApp("/admin/users");
    expect(await screen.findByText("You do not have access to this page.")).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "Administration" });
    expect(within(tabs).getAllByRole("link").map((link) => link.textContent)).toEqual(["My account"]);
  });

  it("creates a user and shows server-side field errors in the form", async () => {
    let created = false;
    mockApi({
      ...shellHandlers(),
      "GET /admin/users": () => ({
        body: {
          items: created ? [user(), user({ id: "2", username: "jordan", display_name: "Jordan Lee", roles: ["analyst"] })] : [user()],
          next_cursor: null,
          total: created ? 2 : 1,
        },
      }),
      "GET /admin/roles": {
        body: {
          items: [
            { id: "r1", name: "administrator", description: "Full access.", is_system: true, permissions: [], member_count: 1 },
            { id: "r2", name: "analyst", description: "Investigation work.", is_system: true, permissions: [], member_count: 0 },
          ],
        },
      },
      "POST /admin/users": (request) => {
        const body = request.body as { username: string };
        if (body.username === "taken") {
          return {
            status: 409,
            body: errorBody("conflict", "That username is already in use.", [{ field: "username", message: "Already in use." }]),
          };
        }
        created = true;
        return { status: 201, body: user({ id: "2", username: "jordan" }) };
      },
    });
    renderApp("/admin/users");
    await userEvent.click(await screen.findByRole("button", { name: "New user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Username"), "taken");
    await userEvent.type(within(dialog).getByLabelText("Initial password"), "a long enough passphrase");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByText("Already in use.")).toBeInTheDocument();

    await userEvent.clear(within(dialog).getByLabelText("Username"));
    await userEvent.type(within(dialog).getByLabelText("Username"), "jordan");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("Jordan Lee")).toBeInTheDocument();
  });
});
