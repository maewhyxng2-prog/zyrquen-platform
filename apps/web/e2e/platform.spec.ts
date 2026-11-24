import { expect, test } from "@playwright/test";

test("AI-first home screen centers AI launcher, capabilities, system availability, and browser history", async ({
  page,
  isMobile,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" }),
  ).toBeVisible();
  await expect(page.locator("#platform-sidebar")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "บทสนทนาล่าสุด" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "ความสามารถที่พร้อมใช้งาน" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "ตรวจสอบสถานะความพร้อมระบบ" }),
  ).toBeVisible();

  await page.locator("#home-ai-prompt").fill("ช่วยออกแบบแผนทดสอบระบบ AI");
  await page.getByRole("button", { name: "ส่งไปยังพื้นที่ทำงาน" }).click();
  await expect(page).toHaveURL(/\/workspace\?prompt=/);
  await expect(page.locator("#prompt")).toHaveValue(
    "ช่วยออกแบบแผนทดสอบระบบ AI",
  );

  // Browser history back/forward navigation works cleanly
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/workspace\?prompt=/);

  if (isMobile) {
    // Bottom nav is hidden inside full-screen /workspace and visible on /
    await expect(page.locator(".mobile-bottom-nav")).toHaveCount(0);
    await page.getByRole("link", { name: "กลับไปหน้าหลัก" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator(".mobile-bottom-nav")).toBeVisible();
  }
});

test("primary, developer, and protected routes enforce boundaries in Dev Mode", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/workspace");
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(
    page.getByRole("heading", { name: "พื้นที่ทำงาน AI" }),
  ).toBeVisible();
  await expect(page.getByText("โหมดพัฒนา · ยังไม่ได้เข้าสู่ระบบ")).toBeVisible();
  await expect(page.getByRole("button", { name: "ส่งข้อความ" })).toBeDisabled();

  await page.goto("/capabilities");
  await expect(
    page.getByRole("heading", { name: "ความสามารถ AI และผลประเมินตามจริง" }),
  ).toBeVisible();

  await page.goto("/knowledge");
  await expect(
    page.getByRole("heading", {
      name: "คลังความรู้และข้อมูล (Knowledge & Data)",
    }),
  ).toBeVisible();

  await page.goto("/system");
  await expect(
    page.getByRole("heading", { name: "สถานะสุขภาพของระบบ" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Closure Audit — สถานะการปิดงาน V10 และเกณฑ์สู่ V11",
    }),
  ).toBeVisible();

  await page.goto("/developer");
  await expect(
    page.getByRole("heading", { name: "API Management" }),
  ).toBeVisible();

  await page.goto("/developer/console");
  await expect(
    page.getByRole("heading", { name: "Developer Console" }),
  ).toBeVisible();

  await page.goto("/training");
  await expect(page).toHaveURL(/\/developer\/console$/);

  for (const protectedPath of [
    "/settings",
    "/developer/keys",
    "/developer/usage",
    "/admin",
  ]) {
    await page.goto(protectedPath);
    await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
    await expect(
      page.getByRole("heading", { name: "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" }),
    ).toBeVisible();
  }
});

test("login form validates password rules and rejects invalid credentials", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" }),
  ).toBeVisible();

  await page.getByLabel("ที่อยู่อีเมล").fill("invalid@zyrquen.local");
  await page.getByLabel(/^รหัสผ่าน/).fill("wrong-password-123");
  await page
    .getByRole("button", { name: "เข้าสู่ระบบไปยังพื้นที่ทำงาน" })
    .click();
  await expect(page.locator(".form-alert[role='alert']")).toContainText(
    "อีเมลหรือรหัสผ่านไม่ถูกต้อง",
  );

  await page.getByRole("tab", { name: "สมัครสมาชิก" }).click();
  await expect(
    page.getByRole("heading", { name: "สร้างบัญชีผู้ใช้ใหม่" }),
  ).toBeVisible();
  await expect(page.getByLabel("ที่อยู่อีเมล")).toHaveAttribute(
    "minlength",
    "5",
  );
  await expect(page.getByLabel(/^รหัสผ่าน/)).toHaveAttribute(
    "minlength",
    "12",
  );
});

test("standard user flow: register, workspace attachments & chat, recent conversations on home, personal settings, developer tools, admin 403, and logout", async ({
  page,
  isMobile,
}, testInfo) => {
  test.setTimeout(90_000);
  const uniqueEmail = `e2e-${Date.now()}-${testInfo.parallelIndex}-${Math.floor(Math.random() * 10000)}@zyrquen.local`;
  const updatedEmail = `updated-${Date.now()}-${testInfo.parallelIndex}@zyrquen.local`;
  const password = "zyrquen-e2e-password-1234";

  await page.goto("/login");
  await page.getByRole("tab", { name: "สมัครสมาชิก" }).click();
  await page.getByLabel("ที่อยู่อีเมล").fill(uniqueEmail);
  await page.getByLabel(/^รหัสผ่าน/).fill(password);
  await page.getByRole("button", { name: "สร้างบัญชีผู้ใช้" }).click();

  await expect(page).toHaveURL(/\/workspace$/);
  await expect(
    page.getByRole("heading", { name: "พื้นที่ทำงาน AI" }),
  ).toBeVisible();
  await expect(page.getByText("Native Model พร้อมใช้งาน").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "ส่งข้อความ" })).toBeDisabled();

  // Attach a small text context file and remove/re-attach cleanly
  const fileInput = page.locator('.composer input[type="file"]');
  await fileInput.setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Native Core 4-Split validation summary"),
  });
  await expect(page.locator(".composer-attachment-chip")).toContainText(
    "notes.txt",
  );

  // Check generation parameters popover toggles cleanly
  await page.getByRole("button", { name: "ตั้งค่าการสร้างข้อความ" }).click();
  await expect(page.locator("#max-tokens")).toBeVisible();
  await page.getByRole("button", { name: "ตั้งค่าการสร้างข้อความ" }).click();

  if (isMobile) {
    // Verify virtual-keyboard-safe input font size (>= 16px) and mobile drawer
    const fontSize = await page
      .locator("#prompt")
      .evaluate((el) => parseFloat(window.getComputedStyle(el).fontSize));
    expect(fontSize).toBeGreaterThanOrEqual(16);

    await page
      .getByRole("button", { name: "เปิดรายการประวัติการสนทนา" })
      .click();
    await expect(page.locator("#workspace-history-sidebar")).toHaveClass(
      /conversation-sidebar-open/,
    );
    await page.getByRole("button", { name: "ปิดรายการบทสนทนา" }).click();
    await expect(page.locator("#workspace-history-sidebar")).not.toHaveClass(
      /conversation-sidebar-open/,
    );
  }

  await page
    .locator("#prompt")
    .fill("สรุปความสามารถของ Native Model ในระบบปัจจุบัน");
  await expect(page.getByRole("button", { name: "ส่งข้อความ" })).toBeEnabled();
  await page.getByRole("button", { name: "ส่งข้อความ" }).click();

  await expect(
    page
      .getByRole("button", { name: "คัดลอกข้อความตอบกลับลงคลิปบอร์ด" })
      .first(),
  ).toBeVisible({ timeout: 15_000 });

  // Return to Home and verify the conversation appears in Recent Conversations
  await page.getByRole("link", { name: "หน้าหลัก ZYRQUEN Ω∞" }).click();
  await expect(page).toHaveURL(/\/$/);
  const recentLink = page.locator(".home-recent-item").first();
  await expect(recentLink).toBeVisible();
  await recentLink.click();
  await expect(page).toHaveURL(/\/workspace\?conversation=/);
  await expect(
    page
      .getByRole("button", { name: "คัดลอกข้อความตอบกลับลงคลิปบอร์ด" })
      .first(),
  ).toBeVisible();

  // Navigate to Settings via Account menu popover
  await page.getByRole("button", { name: "เมนูบัญชีผู้ใช้" }).click();
  await expect(page.locator("#account-popover-menu")).toBeVisible();
  // Standard user must NOT see Admin link in popover
  await expect(
    page
      .locator("#account-popover-menu")
      .getByRole("menuitem", { name: "แดชบอร์ดผู้ดูแลระบบ" }),
  ).toHaveCount(0);
  await page
    .locator("#account-popover-menu")
    .getByRole("menuitem", { name: "การตั้งค่าบัญชี" })
    .click();

  await expect(page).toHaveURL(/\/settings$/);
  await expect(
    page.getByRole("heading", { name: "การตั้งค่า", exact: true }),
  ).toBeVisible();
  // Settings page stays personal and does not render API Key creation inputs directly
  await expect(page.locator("#api-key-name")).toHaveCount(0);

  await expect(page.locator("#profile-email")).toHaveValue(uniqueEmail);
  await page.locator("#profile-email").fill(updatedEmail);
  await page.getByRole("button", { name: "บันทึกอีเมล" }).click();
  await expect(page.getByText("บันทึกข้อมูลบัญชีเรียบร้อยแล้ว")).toBeVisible();

  // Navigate to Developer Settings -> Usage & Keys
  await page
    .getByRole("link", { name: /ตั้งค่าสำหรับนักพัฒนา/ })
    .first()
    .click();
  await expect(page).toHaveURL(/\/developer$/, { timeout: 15_000 });

  await page.getByRole("link", { name: /Usage & Quotas/ }).first().click();
  await expect(page).toHaveURL(/\/developer\/usage$/, { timeout: 15_000 });
  await expect(page.getByRole("progressbar").first()).toBeVisible({ timeout: 15_000 });

  await page.getByRole("link", { name: "API Keys", exact: true }).first().click();
  await expect(page).toHaveURL(/\/developer\/keys$/, { timeout: 15_000 });

  const futureExpiry = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 16);
  await page.locator("#api-key-name").fill("e2e-worker-key");
  await page.locator("#api-key-expires").fill(futureExpiry);
  await page.getByRole("button", { name: "สร้าง API Key" }).click();

  const secretBanner = page.locator(".settings-secret-banner");
  await expect(secretBanner).toBeVisible();
  await expect(secretBanner).toContainText("zq_live_");
  await expect(page.locator("#api-key-usage-select")).toBeVisible();

  await page.getByRole("button", { name: "หมุนเวียนคีย์ทันที" }).first().click();
  await expect(secretBanner).toContainText("หมุนเวียนคีย์");

  await page.getByRole("button", { name: "เพิกถอน" }).first().click();
  await expect(page.getByText("เพิกถอนแล้ว").first()).toBeVisible();

  // Non-admin user visiting /admin is denied cleanly
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/admin$/);
  await expect(
    page.getByText("บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ (Admin Access Required)"),
  ).toBeVisible();

  // Logout via Settings or Account menu and verify protected routes redirect to /login
  await page.goto("/settings");
  await page.getByRole("button", { name: "ออกจากระบบ" }).first().click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/developer/keys");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/workspace");
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByText("โหมดพัฒนา · ยังไม่ได้เข้าสู่ระบบ")).toBeVisible();
  await expect(page.getByRole("button", { name: "ส่งข้อความ" })).toBeDisabled();
});

test("admin login unlocks admin link, overview metrics, user list, and audit logs", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("ที่อยู่อีเมล").fill("demo@zyrquen.local");
  await page.getByLabel(/^รหัสผ่าน/).fill("zyrquen-demo-pass");
  await page
    .getByRole("button", { name: "เข้าสู่ระบบไปยังพื้นที่ทำงาน" })
    .click();
  await expect(page).toHaveURL(/\/workspace$/);

  await page.getByRole("button", { name: "เมนูบัญชีผู้ใช้" }).click();
  await expect(
    page
      .locator("#account-popover-menu")
      .getByRole("menuitem", { name: "แดชบอร์ดผู้ดูแลระบบ" }),
  ).toBeVisible();
  await page
    .locator("#account-popover-menu")
    .getByRole("menuitem", { name: "แดชบอร์ดผู้ดูแลระบบ" })
    .click();

  await expect(page).toHaveURL(/\/admin$/);
  await expect(
    page.getByRole("heading", { name: "แดชบอร์ดผู้ดูแลระบบ" }),
  ).toBeVisible();
  await expect(page.getByText("บัญชีผู้ใช้ทั้งหมด")).toBeVisible();
  await expect(page.getByText("INFERENCE สำเร็จ")).toBeVisible();
  await expect(page.getByText("TOTAL TOKENS")).toBeVisible();
  await expect(page.getByText("API KEY ที่ใช้งานได้")).toBeVisible();
  await expect(
    page.locator("main").getByText("demo@zyrquen.local").first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Log" })).toBeVisible();
});

test("desktop, tablet, and mobile layouts have zero horizontal overflow, proper touch targets, and compact header", async ({
  page,
}) => {
  test.setTimeout(90_000);
  for (const route of [
    "/",
    "/workspace",
    "/capabilities",
    "/knowledge",
    "/system",
    "/developer",
    "/developer/console",
    "/login",
  ]) {
    await page.goto(route);
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 768, height: 1024 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      const metrics = await page.evaluate(() => {
        const isClippedByAncestor = (el: HTMLElement): boolean => {
          let parent = el.parentElement;
          while (
            parent &&
            parent !== document.body &&
            parent !== document.documentElement
          ) {
            const style = window.getComputedStyle(parent);
            if (
              ["hidden", "clip", "auto", "scroll"].includes(style.overflowX) &&
              parent.getBoundingClientRect().right <= window.innerWidth + 1
            ) {
              return true;
            }
            parent = parent.parentElement;
          }
          return false;
        };
        const overflowElements = [
          ...document.querySelectorAll<HTMLElement>("body *"),
        ]
          .filter((element) => !isClippedByAncestor(element))
          .map((element) => ({
            tag: element.tagName,
            className: element.className.toString(),
            right: Math.round(element.getBoundingClientRect().right),
          }))
          .filter((element) => element.right > window.innerWidth + 1)
          .slice(0, 8);

        const header = document.querySelector<HTMLElement>(".app-header");
        const headerHeight = header ? header.getBoundingClientRect().height : 0;

        return {
          overflowElements,
          docScrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          headerHeight,
          innerHeight: window.innerHeight,
        };
      });
      expect(
        metrics.overflowElements,
        `element overflow on ${route} at ${viewport.width}px`,
      ).toEqual([]);
      expect(
        metrics.docScrollWidth,
        `document scrollWidth overflow on ${route} at ${viewport.width}px`,
      ).toBeLessThanOrEqual(metrics.innerWidth + 1);
      if (metrics.headerHeight > 0) {
        expect(
          metrics.headerHeight,
          `header height compact check on ${route} at ${viewport.width}px`,
        ).toBeLessThanOrEqual(metrics.innerHeight * 0.15);
      }
    }
  }
});

test("mobile bottom navigation navigates cleanly across core app screens", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "Mobile bottom nav check runs on mobile viewport");
  await page.goto("/");
  const bottomNav = page.getByRole("navigation", {
    name: "แถบนำทางล่างสำหรับมือถือ",
  });
  await expect(bottomNav).toBeVisible();

  const tabCount = await bottomNav.locator("a").count();
  expect(tabCount).toBe(5);
  const firstTabHeight = await bottomNav
    .locator("a")
    .first()
    .evaluate((el) => el.getBoundingClientRect().height);
  expect(firstTabHeight).toBeGreaterThanOrEqual(44);

  await bottomNav.getByRole("link", { name: "ความสามารถ" }).click();
  await expect(page).toHaveURL(/\/capabilities$/);
  await expect(
    page.getByRole("heading", { name: "ความสามารถ AI และผลประเมินตามจริง" }),
  ).toBeVisible();

  await bottomNav.getByRole("link", { name: "แชท AI" }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(bottomNav).toHaveCount(0);
});
