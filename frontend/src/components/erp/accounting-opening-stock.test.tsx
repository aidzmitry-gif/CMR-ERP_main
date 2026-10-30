import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OpeningWorkspace } from "./accounting-opening-stock";

const context = { organization_id: 1, opening_date: "2026-07-01", policy_id: 1, physical_stock_updated: false,
  existing_opening_entries: 0, inventory_accounts: [{ code: "41", title: "Товары" }],
  counter_accounts: [{ code: "80", title: "Капитал" }], warehouses: [{ name: "warehouse", title: "Склад тестовый" }] };
afterEach(() => vi.unstubAllGlobals());

async function fill() {
  await screen.findByLabelText("Счёт запасов");
  for (const [label, value] of [["Счёт запасов", "41"], ["Корреспондирующий счёт", "80"],
    ["Основание", "Synthetic report"], ["Товар 1", "SKU"], ["Склад 1", "warehouse"],
    ["Партия 1", "opening"], ["Количество 1", "3"], ["Себестоимость 1", "12.34"]])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function mockApi(confirm: "lost-once" | "reject" = "lost-once") {
  let attempts = 0;
  return vi.fn(async (url: string, options?: RequestInit) => {
    if (url.includes("context?")) return { ok: true, json: async () => context };
    const body = JSON.parse(String(options?.body));
    const document = body.document ?? body;
    const result = { organization_id: 1, request_key: document.request_key, opening_date: document.opening_date,
      preview_digest: "a".repeat(64), rows: document.rows.map((r: object) => ({ ...r, unit: "шт", sku_title: "Тестовый товар" })),
      row_count: document.rows.length, total_byn: "12.34", confirmed: url.endsWith("confirm"),
      entry_ids: url.endsWith("confirm") ? [7] : [], physical_stock_updated: false, cutover_finalized: false };
    if (url.endsWith("confirm")) {
      if (confirm === "reject") return { ok: false, status: 422, json: async () => ({ detail: "Данные изменились" }) };
      if (++attempts === 1) throw new Error("network");
    }
    return { ok: true, json: async () => result };
  });
}

it("keeps rows in a review before posting and retries with the identical document key", async () => {
  const fetch = mockApi(); vi.stubGlobal("fetch", fetch);
  render(<OpeningWorkspace org={1} />); await fill();
  fireEvent.click(screen.getByRole("button", { name: "Проверить документ" }));
  await screen.findByText("Результат проверки");
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith("confirm"))).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Записать начальные остатки" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Количество 1")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение с тем же ключом" }));
  await screen.findByText("Остатки записаны в бухгалтерский учёт");
  const calls = fetch.mock.calls.filter(([url]) => String(url).endsWith("confirm"));
  expect(calls).toHaveLength(2);
  expect(calls[0][1]?.body).toBe(calls[1][1]?.body);
  expect(screen.getByText(/Текущее складское наличие не изменялось/)).toBeInTheDocument();
});

it("rechecks context before restoring editing after a transactional rejection", async () => {
  const api = mockApi("reject");
  let contextRequests = 0;
  let refreshContext!: (response: unknown) => void;
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => {
    if (url.includes("context?") && ++contextRequests > 1)
      return new Promise(resolve => { refreshContext = resolve; });
    return api(url, options);
  }));
  render(<OpeningWorkspace org={1} />); await fill();
  fireEvent.click(screen.getByRole("button", { name: "Проверить документ" }));
  await screen.findByText("Результат проверки");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Записать начальные остатки" }));
  await screen.findByText("Данные изменились");
  await waitFor(() => expect(refreshContext).toBeDefined());
  expect(screen.queryByLabelText("Количество 1")).not.toBeInTheDocument();
  expect(screen.queryByText("Результат проверки")).not.toBeInTheDocument();
  await act(async () => {
    refreshContext({ ok: true, json: async () => context });
  });
  const quantity = await screen.findByLabelText("Количество 1");
  expect(quantity).not.toBeDisabled();
  expect(quantity).toHaveValue("3");
});

it("shows a preflight block before allowing data entry", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: "Обычные проводки уже есть" }) })));
  render(<OpeningWorkspace org={1} />);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Обычные проводки уже есть"));
  expect(screen.queryByRole("button", { name: "Проверить документ" })).not.toBeInTheDocument();
});

it("blocks posting while a draft file is still being read", async () => {
  vi.stubGlobal("fetch", mockApi());
  render(<OpeningWorkspace org={1} />); await fill();
  fireEvent.click(screen.getByRole("button", { name: "Проверить документ" }));
  await screen.findByText("Результат проверки");
  fireEvent.click(screen.getByRole("checkbox"));
  let resolve!: (text: string) => void;
  const file = { size: 100, text: () => new Promise<string>(done => { resolve = done; }) };
  fireEvent.change(screen.getByLabelText("Загрузить черновик"), { target: { files: [file] } });
  expect(screen.getByRole("button", { name: "Проверить документ" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Записать начальные остатки" })).toBeDisabled();
  resolve("{}");
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Проверить документ" })).not.toBeDisabled();
});

it("can check a saved document even when new opening entry is now blocked", async () => {
  const api = mockApi();
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => url.includes("context?")
    ? { ok: false, status: 422, json: async () => ({ detail: "Ввод закрыт" }) } : api(url, options)));
  render(<OpeningWorkspace org={1} />); await screen.findByRole("alert");
  const document = { request_key: "00000000-0000-4000-8000-000000000001", opening_date: "2026-07-01", policy_id: 9,
    inventory_account: "41", counter_account: "80", evidence: "Synthetic report", rows: [{ sku: "SKU", warehouse: "warehouse", lot: "opening", quantity: "3", amount_byn: "12.34" }] };
  const file = { size: 100, text: async () => JSON.stringify({ format: "opening-stock-draft-v1", organization_id: 1, document }) };
  fireEvent.change(screen.getByLabelText("Загрузить черновик"), { target: { files: [file] } });
  const check = await screen.findByRole("button", { name: "Проверить загруженный документ" });
  await waitFor(() => expect(check).not.toBeDisabled()); fireEvent.click(check);
  await screen.findByText("Результат проверки");
  expect(JSON.parse(String(api.mock.calls[0][1]?.body)).policy_id).toBe(9);
});

it("keeps the selected date and policy when earlier context arrives last", async () => {
  const api = mockApi();
  let august!: (response: unknown) => void;
  let september!: (response: unknown) => void;
  vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) => {
    if (url.includes("context?on=2026-08-01")) return new Promise(done => { august = done; });
    if (url.includes("context?on=2026-09-01")) return new Promise(done => { september = done; });
    return api(url, options);
  }));
  render(<OpeningWorkspace org={1} />); await screen.findByLabelText("Счёт запасов");
  fireEvent.change(screen.getByLabelText("Дата остатков"), { target: { value: "2026-08-01" } });
  expect(screen.queryByLabelText("Счёт запасов")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Дата остатков"), { target: { value: "2026-09-01" } });
  september({ ok: true, json: async () => ({ ...context, opening_date: "2026-09-01", policy_id: 3 }) });
  await screen.findByLabelText("Счёт запасов");
  august({ ok: true, json: async () => ({ ...context, opening_date: "2026-08-01", policy_id: 2 }) });
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Проверить документ" }));
  await screen.findByText("Результат проверки");
  const preview = api.mock.calls.find(([url]) => url.endsWith("preview"));
  expect(JSON.parse(String(preview?.[1]?.body))).toMatchObject({ opening_date: "2026-09-01", policy_id: 3 });
  expect(screen.getByLabelText("Дата остатков")).toHaveValue("2026-09-01");
});
