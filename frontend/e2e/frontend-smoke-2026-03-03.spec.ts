import { expect, test } from "@playwright/test";

const BASE_URL = process.env.FRONTEND_URL || "http://127.0.0.1:5177";
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || "";
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || process.env.SEED_ADMIN_PASSWORD || "";
const MEMBER_EMAIL = process.env.MEMBER_EMAIL || "";
const MEMBER_PASSWORD = process.env.MEMBER_PASSWORD || process.env.SEED_MEMBER_PASSWORD || "";

const ROUTES = [
  "/login",
  "/dashboard",
  "/executive",
  "/clients",
  "/clients/:id",
  "/tasks",
  "/projects",
  "/projects/:id",
  "/leads",
  "/leads/:id",
  "/proposals",
  "/timesheet",
  "/dailys",
  "/digests",
  "/reports",
  "/growth",
  "/finance",
  "/finance/income",
  "/finance/expenses",
  "/finance/taxes",
  "/finance/forecasts",
  "/finance/advisor",
  "/finance-holded",
  "/users",
  "/discord",
  "/capacity",
];

async function login(page: import("@playwright/test").Page, email: string, password: string) {
  if (!email || !password) {
    throw new Error(`Missing credentials for ${email || "unknown user"}. Set ADMIN_/MEMBER_ or SEED_ env vars before running the smoke audit.`);
  }
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.getByRole("button", { name: /entrar/i }).click();
  await page.waitForURL(/\/dashboard(?:$|\?)/, { timeout: 45_000 });
}

async function waitForAppShell(page: import("@playwright/test").Page) {
  await page.waitForFunction(
    () => !document.body.innerText.includes("Cargando..."),
    { timeout: 45_000 },
  );
  await page.waitForTimeout(800);
}

async function resolveDynamicIds(page: import("@playwright/test").Page) {
  return await page.evaluate(async () => {
    async function safeJson(url: string) {
      try {
        const r = await fetch(url, { credentials: "include" });
        if (!r.ok) return null;
        return await r.json();
      } catch {
        return null;
      }
    }
    const clients = await safeJson("/api/clients?page=1&page_size=1");
    const projects = await safeJson("/api/projects?page=1&page_size=1");
    const leads = await safeJson("/api/leads");
    return {
      clientId: clients?.items?.[0]?.id ?? null,
      projectId: projects?.items?.[0]?.id ?? null,
      leadId: Array.isArray(leads) ? leads?.[0]?.id ?? null : null,
    };
  });
}

function materializeRoute(route: string, ids: { clientId: number | null; projectId: number | null; leadId: number | null }) {
  if (route === "/clients/:id") return ids.clientId ? `/clients/${ids.clientId}` : null;
  if (route === "/projects/:id") return ids.projectId ? `/projects/${ids.projectId}` : null;
  if (route === "/leads/:id") return ids.leadId ? `/leads/${ids.leadId}` : null;
  return route;
}

test.describe("Frontend smoke completo", () => {
  test("admin: todas las rutas cargan sin crash", async ({ page }) => {
    test.setTimeout(8 * 60 * 1000);
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await waitForAppShell(page);
    const ids = await resolveDynamicIds(page);

    const failures: string[] = [];

    for (const route of ROUTES) {
      const resolved = materializeRoute(route, ids);
      if (!resolved) continue;

      const pageErrors: string[] = [];
      const api5xx: string[] = [];
      const navErrors: string[] = [];

      const onPageError = (err: Error) => pageErrors.push(err.message);
      const onResponse = (resp: import("@playwright/test").Response) => {
        if (resp.url().includes("/api/") && resp.status() >= 500) {
          api5xx.push(`${resp.status()} ${resp.url()}`);
        }
      };

      page.on("pageerror", onPageError);
      page.on("response", onResponse);

      try {
        await page.goto(`${BASE_URL}${resolved}`, {
          waitUntil: "domcontentloaded",
          timeout: 45_000,
        });
        await page.waitForTimeout(1200);
      } catch (e) {
        navErrors.push(String(e));
      } finally {
        page.off("pageerror", onPageError);
        page.off("response", onResponse);
      }

      const bodyText = (await page.locator("body").innerText()).slice(0, 3000);
      const hasBoundaryCrash = bodyText.includes("Algo salió mal");

      if (navErrors.length || pageErrors.length || api5xx.length || hasBoundaryCrash) {
        failures.push(
          `${resolved} | navErrors=${navErrors.join(" || ") || "-"} | pageErrors=${pageErrors.join(" || ") || "-"} | api5xx=${api5xx.join(" || ") || "-"} | boundary=${hasBoundaryCrash}`,
        );
      }
    }

    expect(failures, failures.join("\n")).toEqual([]);
  });

  test("member: sidebar restringida y /leads bloqueado", async ({ page }) => {
    test.setTimeout(3 * 60 * 1000);
    await login(page, MEMBER_EMAIL, MEMBER_PASSWORD);
    await page.goto(`${BASE_URL}/dashboard`, { waitUntil: "domcontentloaded" });
    await waitForAppShell(page);

    // Desktop sidebar (aside) + mobile bottom nav fallback.
    const sidebarItems = await page.$$eval("aside a, nav a", (els) =>
      els
        .map((el) => (el.textContent || "").replace(/\s+/g, " ").trim())
        .filter(Boolean),
    );

    const shouldBeVisible = ["Dashboard", "Clientes", "Tareas", "Proyectos", "Timesheet", "Dailys"];
    const shouldBeHidden = ["Pipeline", "Presupuestos", "Facturacion", "Growth", "Informes", "Digests", "Ejecutivo", "Equipo", "Discord", "Capacidad"];

    const missingVisible = shouldBeVisible.filter((x) => !sidebarItems.includes(x));
    const presentHidden = shouldBeHidden.filter((x) => sidebarItems.includes(x));

    expect(missingVisible, `Sidebar member missing: ${missingVisible.join(", ")}`).toEqual([]);
    expect(presentHidden, `Sidebar member forbidden: ${presentHidden.join(", ")}`).toEqual([]);

    const apiResponses: Array<{ url: string; status: number }> = [];
    const onResponse = (resp: import("@playwright/test").Response) => {
      if (resp.url().includes("/api/leads")) {
        apiResponses.push({ url: resp.url(), status: resp.status() });
      }
    };
    page.on("response", onResponse);
    await page.goto(`${BASE_URL}/leads`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1200);
    page.off("response", onResponse);

    const finalUrl = page.url();
    const deniedBy403 = apiResponses.some((r) => r.status === 403);
    const redirected = !finalUrl.endsWith("/leads");
    const accessDeniedVisible = await page.getByText(/acceso restringido/i).isVisible().catch(() => false);

    expect(
      deniedBy403 || redirected || accessDeniedVisible,
      `Expected /leads blocked for member. finalUrl=${finalUrl} api=${JSON.stringify(apiResponses)} accessDenied=${accessDeniedVisible}`,
    ).toBeTruthy();
  });
});
