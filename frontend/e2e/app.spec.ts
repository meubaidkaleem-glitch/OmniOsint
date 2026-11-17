import { expect, test, type Page } from "@playwright/test";

/**
 * One continuous journey through the Phase 1 interface against the real
 * backend: first-run setup, dashboard, planned sections, administration,
 * audit trail, a second user with a forced password change, and sign-out.
 */

const ADMIN = { username: "admin", password: "correct horse battery staple" };
const ANALYST = { username: "jordan", temporary: "temporary passphrase 1", final: "a brand new passphrase" };
const shots = process.env.OMNIOSINT_E2E_SCREENSHOTS;

async function capture(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: false });
}

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((url) => url.pathname !== "/login");
}

test.describe.serial("Phase 1 interface", () => {
  test("first-run setup creates the administrator and signs in", async ({ page }) => {
    const setupUrl = process.env.OMNIOSINT_E2E_SETUP_URL;
    test.skip(!setupUrl, "OMNIOSINT_E2E_SETUP_URL is not set");
    await page.goto(setupUrl!);
    await expect(page.getByRole("heading", { name: "First-run setup" })).toBeVisible();
    await expect(page.getByLabel("Setup token")).not.toHaveValue("");
    expect(page.url()).not.toContain("#token=");
    await capture(page, "01-setup");

    await page.getByLabel("Username").fill(ADMIN.username);
    await page.getByLabel("Display name").fill("Morgan Admin");
    await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
    await page.getByLabel("Confirm password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Create administrator" }).click();

    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "System health", exact: true })).toBeVisible();
    await capture(page, "02-dashboard");

    // Setup cannot be repeated.
    await page.goto("/setup");
    await expect(page.getByRole("heading", { name: "Sign in" }).or(page.getByRole("heading", { name: "Dashboard" }))).toBeVisible();
  });

  test("the dashboard reports real records and unavailable metrics honestly", async ({ page }) => {
    await signIn(page, ADMIN.username, ADMIN.password);
    await expect(page.getByText("Active user accounts")).toBeVisible();
    const notYet = page.locator("section", { has: page.getByRole("heading", { name: "Not yet available" }) });
    await expect(notYet.getByText("Total investigations")).toBeVisible();
    await expect(notYet.getByText("Phase 3").first()).toBeVisible();
    await expect(page.getByText(/No provider integration is implemented yet/)).toBeVisible();
  });

  test("navigation has twenty sections and planned ones say so", async ({ page }) => {
    await signIn(page, ADMIN.username, ADMIN.password);
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link")).toHaveCount(20);
    await nav.getByRole("link", { name: /Internet Asset Intelligence/ }).click();
    await expect(page.getByRole("heading", { name: "Internet Asset Intelligence" })).toBeVisible();
    await expect(page.getByRole("main").getByText("Planned — not yet implemented").first()).toBeVisible();
    await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
    await capture(page, "03-planned-section");

    await nav.getByRole("link", { name: "Integrations" }).click();
    await expect(page.getByRole("heading", { name: /catalogued sources/ })).toBeVisible();
    await expect(page.getByText("0 available", { exact: false })).toBeVisible();
    await capture(page, "04-integrations");
  });

  test("an administrator creates a user, and it is audited", async ({ page }) => {
    await signIn(page, ADMIN.username, ADMIN.password);
    await page.goto("/admin/users");
    await page.getByRole("button", { name: "New user" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Username").fill(ANALYST.username);
    await dialog.getByLabel("Display name").fill("Jordan Lee");
    await dialog.getByLabel("Initial password").fill("short");
    await dialog.getByRole("button", { name: "Create user" }).click();
    await expect(dialog.getByText("Use at least 12 characters.")).toBeVisible();
    await dialog.getByLabel("Initial password").fill(ANALYST.temporary);
    await dialog.getByRole("button", { name: "Create user" }).click();
    await expect(dialog).toBeHidden();
    const row = page.getByRole("row", { name: /Jordan Lee/ });
    await expect(row.getByText("Password change due")).toBeVisible();
    await capture(page, "05-users");

    await page.getByRole("link", { name: "Audit log" }).click();
    await expect(page.getByRole("cell", { name: "user.created" })).toBeVisible();
    await page.getByRole("cell", { name: "user.created" }).click();
    await expect(page.getByRole("dialog").getByText('"username": "jordan"')).toBeVisible();
    await capture(page, "06-audit-detail");
    await page.keyboard.press("Escape");

    await page.getByRole("link", { name: "System status" }).click();
    await expect(page.getByRole("heading", { name: "Components" })).toBeVisible();
    await expect(page.getByRole("cell", { name: /PostgreSQL database/ })).toBeVisible();
    await capture(page, "07-system-status");
  });

  test("a new user must change the temporary password and sees only what they may", async ({ page }) => {
    await signIn(page, ANALYST.username, ANALYST.temporary);
    await expect(page.getByRole("heading", { name: "Change your password" })).toBeVisible();
    await page.getByLabel("Current password").fill(ANALYST.temporary);
    await page.getByLabel("New password", { exact: true }).fill(ANALYST.final);
    await page.getByLabel("Confirm new password").fill(ANALYST.final);
    await page.getByRole("button", { name: "Change password" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.goto("/admin");
    const tabs = page.getByRole("navigation", { name: "Administration" });
    await expect(tabs.getByRole("link")).toHaveText(["My account"]);
    await page.goto("/admin/users");
    await expect(page.getByText("You do not have access to this page.")).toBeVisible();
  });

  test("command palette, theme and sign-out", async ({ page }) => {
    await signIn(page, ADMIN.username, ADMIN.password);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await page.keyboard.press("Control+k");
    await page.getByPlaceholder("Type a section or action…").fill("relationship");
    await capture(page, "08-command-palette");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Relationship Graph" })).toBeVisible();

    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Light theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "System health", exact: true })).toBeVisible();
    await capture(page, "09-dashboard-light");

    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await page.goto("/admin/users");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});
