import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { authState, dashboard, providerList, shellHandlers } from "@/test/fixtures";
import { errorBody, mockApi, renderApp } from "@/test/utils";

const signedOut = {
  "GET /auth/me": { status: 401, body: errorBody("authentication_required", "Sign in to continue.") },
  "GET /system/health/live": { body: { status: "ok" } },
};

describe("route guard", () => {
  it("sends a fresh installation to first-run setup", async () => {
    mockApi({
      ...signedOut,
      "GET /system/info": { body: { service: "omniosint", version: "0.1.0", api_version: "v1", setup_required: true } },
      "GET /auth/setup-status": { body: { setup_required: true, token_file: "C:\\Users\\me\\setup-token.txt" } },
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "First-run setup" })).toBeInTheDocument();
    expect(await screen.findByText("C:\\Users\\me\\setup-token.txt")).toBeInTheDocument();
  });

  it("sends a signed-out user to the sign-in page", async () => {
    mockApi({
      ...signedOut,
      "GET /system/info": { body: { service: "omniosint", version: "0.1.0", api_version: "v1", setup_required: false } },
    });
    const { router } = renderApp("/admin/users");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
  });

  it("requires a password change before anything else", async () => {
    mockApi({ ...shellHandlers(authState({ user: { must_change_password: true } })) });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Change your password" })).toBeInTheDocument();
  });
});

describe("dashboard", () => {
  it("shows record counts and never reports unavailable metrics as zero", async () => {
    mockApi({ ...shellHandlers(), "GET /dashboard": { body: dashboard() } });
    renderApp("/");
    expect(await screen.findByText("Active user accounts")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    const notYet = screen.getByRole("heading", { name: "Not yet available" }).closest("section");
    expect(notYet).not.toBeNull();
    const panel = within(notYet as HTMLElement);
    expect(panel.getByText("Total investigations")).toBeInTheDocument();
    expect(panel.getByText("Phase 3")).toBeInTheDocument();
    expect(panel.queryByText("0")).toBeNull();
    expect(screen.getByText(/No provider integration is implemented yet/)).toBeInTheDocument();
  });

  it("shows the error and request id when loading fails", async () => {
    mockApi({
      ...shellHandlers(),
      "GET /dashboard": { status: 500, body: errorBody("internal_error", "An unexpected error occurred.") },
    });
    renderApp("/");
    expect(await screen.findByText("An unexpected error occurred.", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/req-test-1/)).toBeInTheDocument();
  });
});

describe("planned sections", () => {
  it("state the plan and offer no controls", async () => {
    mockApi(shellHandlers());
    renderApp("/threat");
    expect(await screen.findByRole("heading", { name: "Threat Intelligence" })).toBeInTheDocument();
    const main = screen.getByRole("main");
    expect(within(main).getAllByText("Planned — not yet implemented").length).toBeGreaterThan(0);
    expect(within(main).getByText("Threat Intelligence capability one")).toBeInTheDocument();
    expect(within(main).queryAllByRole("button")).toHaveLength(0);
    expect(within(main).queryAllByRole("textbox")).toHaveLength(0);
  });

  it("marks planned sections in the sidebar", async () => {
    mockApi(shellHandlers());
    renderApp("/threat");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    await waitFor(() =>
      expect(within(nav).getByRole("link", { name: /Investigations/ })).toHaveAttribute(
        "data-feature-status",
        "planned",
      ),
    );
    expect(within(nav).getAllByRole("link")).toHaveLength(20);
  });
});

describe("integrations", () => {
  it("lists the catalogue with real statuses and filters it", async () => {
    mockApi({
      ...shellHandlers(),
      "GET /providers": { body: providerList() },
      "GET /providers/adapters": { body: { items: [] } },
    });
    renderApp("/integrations");
    expect(await screen.findByText("Shodan")).toBeInTheDocument();
    expect(screen.getByText("No real provider integration is implemented yet")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "excluded");
    expect(screen.queryByText("Shodan")).toBeNull();
    expect(screen.getByText("Cisco Talos")).toBeInTheDocument();
  });
});

describe("command palette", () => {
  it("opens with Ctrl+K and navigates", async () => {
    mockApi({ ...shellHandlers(), "GET /dashboard": { body: dashboard() } });
    const { router } = renderApp("/");
    await screen.findByText("Active user accounts");
    await userEvent.keyboard("{Control>}k{/Control}");
    const input = await screen.findByPlaceholderText(/section/);
    await userEvent.type(input, "vulnerab");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/vulnerability"));
  });

  it("searches for an indicator that matches no section", async () => {
    mockApi({ ...shellHandlers(), "GET /dashboard": { body: dashboard() } });
    const { router } = renderApp("/");
    await screen.findByText("Active user accounts");
    await userEvent.keyboard("{Control>}k{/Control}");
    const input = await screen.findByPlaceholderText(/indicator/);
    await userEvent.type(input, "198.51.100.7");
    expect(screen.getByRole("option", { name: /Search for 198.51.100.7/ })).toBeInTheDocument();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/search"));
    expect(router.state.location.search).toBe("?q=198.51.100.7");
  });

  it("hides administration pages the user may not open", async () => {
    mockApi({ ...shellHandlers(authState({ permissions: [], user: { roles: ["analyst"] } })), "GET /dashboard": { body: dashboard() } });
    renderApp("/");
    await screen.findByText("Active user accounts");
    await userEvent.keyboard("{Control>}k{/Control}");
    await screen.findByPlaceholderText(/section/);
    expect(screen.getByRole("option", { name: /My account/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^Users$/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Audit log/ })).toBeNull();
  });
});
