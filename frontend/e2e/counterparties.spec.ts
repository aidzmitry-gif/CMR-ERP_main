import { expect, test } from "@playwright/test";

test("контрагенты: создание, preview, повторное обогащение и duplicate UNP", async ({ page }) => {
  const demoUnps = ["190445566", "190000002"] as const;
  const retry = test.info().retry;
  if (retry < 0 || retry >= demoUnps.length) {
    throw new Error(`Поддерживаются только попытки E2E 0..${demoUnps.length - 1}, получена ${retry}`);
  }
  const demoUnp = demoUnps[retry];
  const runName = `CRM-CP-001 E2E ${Date.now()}-${test.info().workerIndex}`;
  const editedAddress = `${runName} manual address`;
  const bankName = "CRM E2E Bank";
  const iban = "DE89370400440532013000";
  const bic = "COBADEFFXXX";
  const contactName = "CRM E2E Contact";
  const contactPhone = "+375 29 123-45-67";
  const contactEmail = "contact@example.invalid";

  await test.step("catalog tile ведёт в поиск контрагентов", async () => {
    await page.goto("/erp/spravochniki");
    await expect(page.getByRole("link", { name: "Карточка контрагента" })).toBeVisible();
    await page.getByRole("link", { name: "Карточка контрагента" }).click();
    await expect(page).toHaveURL(/\/erp\/spravochniki\/counterparty$/);
  });

  await test.step("поиск по уникальному имени и inline create", async () => {
    await page.getByLabel("Название").fill(runName);
    await page.getByRole("button", { name: "Найти", exact: true }).click();
    await expect(page.getByText("Совпадений нет.")).toBeVisible();

    await page.getByRole("button", { name: "+ Новый контрагент" }).click();
    const editor = page.getByRole("region", { name: "Новый контрагент" });
    await editor.getByLabel("Наименование компании").fill(runName);
    await editor.getByLabel("УНП (карточка)").fill(demoUnp);
    await editor.getByLabel("Банк").fill(bankName);
    await editor.getByLabel("Счёт IBAN").fill(iban);
    await editor.getByLabel("BIC").fill(bic);
    await editor.getByRole("button", { name: "+ Добавить контакт" }).click();
    await editor.getByLabel("Имя контакта 1").fill(contactName);
    await editor.getByLabel("Телефон контакта 1").fill(contactPhone);
    await editor.getByLabel("Email контакта 1").fill(contactEmail);

    await editor.getByRole("button", { name: "Получить по УНП" }).click();
    const preview = editor.getByRole("group", { name: "Предпросмотр реестра" });
    await expect(preview.getByText(/Источник: Демо-источник/)).toBeVisible();
    const previewValue = async (label: string) => {
      const row = preview.locator("label").filter({ hasText: `${label}:` });
      const valueText = (await row.locator(":scope > span").first().textContent()) ?? "";
      return valueText
        .replace(`${label}:`, "")
        .trim();
    };
    const previewAddress = await previewValue("Юридический адрес");
    const previewStatus = await previewValue("Статус реестра");
    expect(previewAddress).toBeTruthy();
    expect(previewStatus).toBeTruthy();
    await preview.getByRole("checkbox", { name: "Выбрать Юридический адрес" }).check();
    await preview.getByRole("checkbox", { name: "Выбрать Статус реестра" }).check();
    await editor.getByRole("button", { name: "Сохранить" }).click();

    await expect(page).toHaveURL(/\/erp\/spravochniki\/counterparty\/\d+\?name=/);
    const detailUrl = new URL(page.url());
    const createdId = Number(detailUrl.pathname.split("/").pop());
    expect(Number.isSafeInteger(createdId)).toBe(true);
    expect(createdId).toBeGreaterThan(0);
    expect(detailUrl.searchParams.get("name")).toBe(runName);
    expect(detailUrl.searchParams.get("unp")).toBeNull();
    await expect(page.getByRole("heading", { name: runName, exact: true })).toBeVisible();
    await expect(page.getByText(previewAddress, { exact: true })).toBeVisible();
    await expect(page.getByText(previewStatus, { exact: true })).toBeVisible();
    await expect(page.getByText(bankName, { exact: true })).toBeVisible();
    await expect(page.getByText(iban, { exact: true })).toBeVisible();
    await expect(page.getByText(bic, { exact: true })).toBeVisible();
    await expect(page.getByText(contactName, { exact: true })).toBeVisible();
    await expect(page.getByText(contactPhone, { exact: true })).toBeVisible();
    await expect(page.getByText(contactEmail, { exact: true })).toBeVisible();
    const demoBadges = page.locator('[title^="Источник: Демо-источник"]');
    await expect(demoBadges).toHaveCount(2);
    await expect(demoBadges.first()).toBeVisible();

    await test.step("manual address + re-enrich сохраняют bank/contact", async () => {
      const editor = page.getByRole("region", { name: "Редактирование контрагента" });
      await editor.getByRole("button", { name: "Редактировать" }).click();
      await editor.getByLabel("Юридический адрес").fill(editedAddress);
      await editor.getByRole("button", { name: "Получить по УНП" }).click();
      const refreshedPreview = editor.getByRole("group", { name: "Предпросмотр реестра" });
      await expect(refreshedPreview.getByText(/Источник: Демо-источник/)).toBeVisible();
      await expect(refreshedPreview.getByRole("checkbox", { name: "Выбрать Юридический адрес" })).not.toBeChecked();
      await editor.getByRole("button", { name: "Сохранить" }).click();
      await expect(page.getByText(editedAddress, { exact: true })).toBeVisible();
      await expect(page.getByText(bankName, { exact: true })).toBeVisible();
      await expect(page.getByText(contactName, { exact: true })).toBeVisible();
      await expect(page.getByText(contactEmail, { exact: true })).toBeVisible();
    });

    await test.step("no-op save не блокирует повторное редактирование", async () => {
      const editor = page.getByRole("region", { name: "Редактирование контрагента" });
      const editButton = editor.getByRole("button", { name: "Редактировать" });
      await expect(editButton).toBeEnabled();
      await editButton.click();
      await editor.getByRole("button", { name: "Сохранить" }).click();
      await expect(editor.getByRole("button", { name: "Редактировать" })).toBeEnabled();
      await editor.getByRole("button", { name: "Редактировать" }).click();
      await expect(editor.getByLabel("Банк")).toHaveValue(bankName);
      await editor.getByRole("button", { name: "Отмена" }).click();
    });

    await page.screenshot({ path: test.info().outputPath("counterparty-desktop.png"), fullPage: true });

    await test.step("mobile bounds и filled editor screenshot", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await expect(page.getByRole("heading", { name: runName, exact: true })).toBeVisible();
      const editor = page.getByRole("region", { name: "Редактирование контрагента" });
      await editor.getByRole("button", { name: "Редактировать" }).click();
      const unpInput = editor.getByLabel("УНП (карточка)");
      await expect(unpInput).toBeVisible();
      const unpBox = await unpInput.boundingBox();
      expect(unpBox).not.toBeNull();
      expect(unpBox?.width ?? 0).toBeGreaterThan(120);
      expect((unpBox?.x ?? 0) + (unpBox?.width ?? 0)).toBeLessThanOrEqual(330);
      await expect(editor.getByLabel("Банк")).toHaveValue(bankName);
      await expect(editor.getByLabel("Email контакта 1")).toHaveValue(contactEmail);
      await unpInput.scrollIntoViewIfNeeded();
      await page.screenshot({ path: test.info().outputPath("counterparty-mobile.png"), fullPage: true });
      await editor.getByRole("button", { name: "Отмена" }).click();
    });

    await test.step("duplicate UNP сохраняет draft и не уходит со страницы", async () => {
      await page.getByRole("link", { name: "← К поиску контрагентов" }).click();
      await expect(page).toHaveURL(/\/erp\/spravochniki\/counterparty\?name=/);
      await expect(page.getByText(runName, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "+ Новый контрагент" }).click();
      const duplicateEditor = page.getByRole("region", { name: "Новый контрагент" });
      const duplicateName = `${runName} duplicate`;
      await duplicateEditor.getByLabel("Наименование компании").fill(duplicateName);
      await duplicateEditor.getByLabel("УНП (карточка)").fill(demoUnp);
      await duplicateEditor.getByRole("button", { name: "Сохранить" }).click();
      await expect(duplicateEditor.getByRole("alert")).toContainText("Найдите карточку по УНП");
      await expect(duplicateEditor.getByLabel("Наименование компании")).toHaveValue(duplicateName);
      await expect(page).toHaveURL(/\/erp\/spravochniki\/counterparty\?name=/);
      expect(new URL(page.url()).searchParams.get("name")).toBe(runName);
      await expect(page.getByRole("link", { name: String(createdId), exact: true })).toBeVisible();
      await duplicateEditor.getByRole("button", { name: "Отмена" }).click();
    });

    await test.step("real ID link and back preserve search query", async () => {
      await page.getByRole("link", { name: String(createdId), exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`/counterparty/${createdId}\\?name=`));
      expect(new URL(page.url()).searchParams.get("name")).toBe(runName);
      await page.getByRole("link", { name: "← К поиску контрагентов" }).click();
      await expect(page).toHaveURL(/\/erp\/spravochniki\/counterparty\?name=/);
      expect(new URL(page.url()).searchParams.get("name")).toBe(runName);
      await expect(page.getByRole("link", { name: String(createdId), exact: true })).toBeVisible();
    });
  });
});
