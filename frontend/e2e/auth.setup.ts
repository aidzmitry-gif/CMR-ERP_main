import { expect, test as setup } from "@playwright/test";

// Единый dev-логин для всех e2e. AppShell гейтит /crm/* и /erp/*: без cookie сессии
// (aios_user) уводит на /login. Проходим экран входа как Директор (первый в списке —
// полный доступ ко всем модулям) и сохраняем httpOnly-cookie сессии в storageState,
// который переиспользуют остальные проекты — так тесты стартуют уже «вошедшими».
const authFile = "e2e/.auth/state.json";

setup("dev-логин (Директор)", async ({ page }) => {
  await page.goto("/login");
  // Список сотрудников грузится с backend (/system/users); кнопка активна, когда
  // выбран сотрудник. По умолчанию выбран первый — Директор (полный доступ).
  await page.getByRole("button", { name: "Войти" }).click();
  // Успешный вход уводит на доску сделок — дожидаемся, чтобы cookie точно проставился
  // и гейт AppShell пропустил.
  await page.waitForURL("**/crm/deals");
  await expect(page.getByRole("button", { name: /Создать сделку/ })).toBeVisible();
  await page.context().storageState({ path: authFile });
});
