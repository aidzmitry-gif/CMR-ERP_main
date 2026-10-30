import { expect, test } from "@playwright/test";
import { configureInstallationCompany } from "./installation-company";

test("a Settings change blocks the old company's draft and reload adopts the new company", async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  const stamp = Date.now().toString().slice(-6);
  async function company(name: string, prefix: string) {
    const response = await page.request.post("/api/accounting/organizations", { data: { name, unp: `${prefix}${stamp}` } });
    expect(response.ok(), await response.text()).toBeTruthy();
    return response.json();
  }
  const first = await company("Учебная компания А · общая настройка", "985");
  const second = await company("Учебная компания Б · общая настройка", "986");
  await configureInstallationCompany(page, first.id);
  await page.goto("/erp/procurement/planning");
  const item = page.getByLabel("Позиция", { exact: true });
  await expect(item).toBeEnabled();
  await item.fill("Незавершённая заявка компании А");
  const settings = await page.context().newPage();
  try {
    await settings.goto("/erp/settings");
    await settings.getByLabel("Юрлицо для всей платформы").selectOption(String(second.id));
    await settings.getByRole("button", { name: "Сохранить для всей платформы", exact: true }).click();
    await expect(settings.getByRole("status").filter({ hasText: "Сохранено для всей платформы" })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Открытая форма заблокирована" })).toBeVisible();
    await expect(item).toHaveValue("Незавершённая заявка компании А");
    await expect(page.locator("[inert]")).toContainText("Новая заявка");
    await page.screenshot({ path: testInfo.outputPath("stale-company-draft.png"), fullPage: true });
    await page.reload();
    await expect(page.getByText(`${second.name} · УНП ${second.unp}`, { exact: true })).toBeVisible();
    await expect(item).toHaveValue("");
    const configured = await page.request.get("/api/system/instance-organization");
    expect((await configured.json()).organization.id).toBe(second.id);
  } finally { await settings.close(); }
});
