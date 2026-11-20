import { expect, test } from "@playwright/test";

test("dashboard is usable without fabricating backend telemetry", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Command center" })).toBeVisible();
  await expect(page.getByText("Activity data is not exposed")).toBeVisible();
  await expect(page.getByText("No dataset status endpoint")).toBeVisible();
});

test("navigation opens on mobile and reaches the real workspace route", async ({ page, isMobile }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Command center" })).toBeVisible();

  if (isMobile) {
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(page.locator(".sidebar")).toHaveClass(/sidebar-open/);
  }

  await page.getByRole("link", { name: "AI workspace", exact: true }).click();
  await expect(page.getByRole("heading", { name: "AI workspace" })).toBeVisible();
  await expect(page.getByText("This browser only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled();
  await expect(page.getByText("RUNTIME UNAVAILABLE")).toBeVisible();
});

test("system page marks unsupported health endpoints unavailable", async ({ page }) => {
  await page.goto("/system");
  await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
  await expect(page.getByText("No database health endpoint is implemented")).toBeVisible();
  await expect(page.getByText("No storage health endpoint is implemented")).toBeVisible();
});

test("desktop, tablet, and Android layouts do not overflow horizontally", async ({ page }) => {
  await page.goto("/training");
  await expect(page.getByRole("heading", { name: "Training workspace" })).toBeVisible();
  await expect(page.getByText("Planned · not API-integrated").first()).toBeVisible();

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    const overflowElements = await page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>("body *")]
        .map((element) => ({
          tag: element.tagName,
          className: element.className.toString(),
          right: Math.round(element.getBoundingClientRect().right),
        }))
        .filter((element) => element.right > window.innerWidth + 1)
        .slice(0, 8),
    );
    expect(overflowElements, `overflow at ${viewport.width}px`).toEqual([]);
  }
});

test("account form reflects the existing API password requirement", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("tab", { name: "Create account" }).click();
  await expect(page.getByLabel("Email address")).toHaveAttribute("minlength", "5");
  await expect(page.getByLabel("Password")).toHaveAttribute("minlength", "12");
});
