import { expect, test } from "@playwright/test";

test("home page leads with AI Workspace experience, starter prompts, and truthful progress metrics", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /เปิดพื้นที่ทำงาน AI/ }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "ตัวชี้วัดความก้าวหน้า ZYRQUEN Ω∞" }),
  ).toBeVisible();

  await page.getByRole("link", { name: /สำรวจความสามารถของ Native Model/ }).click();
  await expect(page).toHaveURL(/\/workspace\?prompt=/);
  await expect(
    page.getByRole("heading", { name: "พื้นที่ทำงาน AI" }),
  ).toBeVisible();
  await expect(page.locator("#prompt")).toHaveValue(
    "สรุปความสามารถของ Native Model ในระบบปัจจุบัน",
  );
});

test("primary and advanced navigation routes load cleanly with proper auth boundaries in Dev Mode", async ({
  page,
}) => {
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
    page.getByRole("heading", { name: "คลังความรู้และข้อมูล (Knowledge & Data)" }),
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
  await expect(
    page.getByText("ยังไม่มี Endpoint สำหรับตรวจสอบสถานะฐานข้อมูล"),
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
    await expect(page).toHaveURL(/\/login$/);
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
  await page.getByRole("button", { name: "เข้าสู่ระบบไปยังพื้นที่ทำงาน" }).click();
  await expect(page.locator(".form-alert[role='alert']")).toContainText(
    "อีเมลหรือรหัสผ่านไม่ถูกต้อง",
  );

  await page.getByRole("tab", { name: "สมัครสมาชิก" }).click();
  await expect(
    page.getByRole("heading", { name: "สร้างบัญชีผู้ใช้ใหม่" }),
  ).toBeVisible();
  await expect(page.getByLabel("ที่อยู่อีเมล")).toHaveAttribute("minlength", "5");
  await expect(page.getByLabel(/^รหัสผ่าน/)).toHaveAttribute("minlength", "12");
});

test("register, login, AI workspace chat, personal settings, developer API keys, usage & quotas, and logout work end-to-end", async ({
  page,
  isMobile,
}, testInfo) => {
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

  await page.locator("#prompt").fill("สรุปความสามารถของ Native Model ในระบบปัจจุบัน");
  await expect(page.getByRole("button", { name: "ส่งข้อความ" })).toBeEnabled();
  await page.getByRole("button", { name: "ส่งข้อความ" }).click();

  await expect(
    page.getByRole("button", { name: "คัดลอกข้อความตอบกลับลงคลิปบอร์ด" }).first(),
  ).toBeVisible({ timeout: 15_000 });

  if (isMobile) {
    await page.getByRole("button", { name: "เปิดเมนูนำทาง" }).click();
    await expect(page.locator("#platform-sidebar")).toHaveClass(/sidebar-open/);
  }
  await page.getByRole("link", { name: "การตั้งค่า", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(
    page.getByRole("heading", { name: "การตั้งค่า", exact: true }),
  ).toBeVisible();

  await expect(page.locator("#profile-email")).toHaveValue(uniqueEmail);
  await page.locator("#profile-email").fill(updatedEmail);
  await page.getByRole("button", { name: "บันทึกอีเมล" }).click();
  await expect(page.getByText("บันทึกข้อมูลบัญชีเรียบร้อยแล้ว")).toBeVisible();

  await page.getByRole("link", { name: /Usage & Quotas/ }).first().click();
  await expect(page).toHaveURL(/\/developer\/usage$/);
  await expect(page.getByRole("progressbar").first()).toBeVisible();

  await page.getByRole("link", { name: "API Keys", exact: true }).first().click();
  await expect(page).toHaveURL(/\/developer\/keys$/);

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
  await expect(
    page.getByText("กราฟประสิทธิภาพ API Key (7 วันล่าสุด)"),
  ).toBeVisible();

  await page.getByRole("button", { name: "หมุนเวียนคีย์ทันที" }).first().click();
  await expect(secretBanner).toContainText("หมุนเวียนคีย์");

  await page.getByRole("button", { name: "เพิกถอน" }).first().click();
  await expect(page.getByText("เพิกถอนแล้ว").first()).toBeVisible();

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

test("admin login unlocks admin overview, user list, and audit logs", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("ที่อยู่อีเมล").fill("demo@zyrquen.local");
  await page.getByLabel(/^รหัสผ่าน/).fill("zyrquen-demo-pass");
  await page.getByRole("button", { name: "เข้าสู่ระบบไปยังพื้นที่ทำงาน" }).click();
  await expect(page).toHaveURL(/\/workspace$/);

  await page.goto("/admin");
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

test("desktop, tablet, and mobile layouts do not overflow horizontally across restructured routes", async ({
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
        const overflowElements = [...document.querySelectorAll<HTMLElement>("body *")]
          .filter((element) => !isClippedByAncestor(element))
          .map((element) => ({
            tag: element.tagName,
            className: element.className.toString(),
            right: Math.round(element.getBoundingClientRect().right),
          }))
          .filter((element) => element.right > window.innerWidth + 1)
          .slice(0, 8);
        return {
          overflowElements,
          docScrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
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
    }
  }
});

test("mobile navigation drawer opens primary and advanced sections cleanly on small screens", async ({
  page,
  isMobile,
}) => {
  test.skip(!isMobile, "Mobile drawer check runs on mobile viewport");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "ยินดีต้อนรับสู่ ZYRQUEN Ω∞" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "เปิดเมนูนำทาง" }).click();
  await expect(page.locator("#platform-sidebar")).toHaveClass(/sidebar-open/);
  await Promise.all([
    page.waitForURL(/\/capabilities$/, { timeout: 15_000 }),
    page.getByRole("link", { name: "ความสามารถ AI", exact: true }).click(),
  ]);
  await expect(
    page.getByRole("heading", { name: "ความสามารถ AI และผลประเมินตามจริง" }),
  ).toBeVisible();
});
