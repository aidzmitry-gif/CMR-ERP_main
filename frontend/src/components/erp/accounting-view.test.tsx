import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./expense-control", () => ({ ExpenseControl: ({org}: {org?: string}) => <section aria-label="Общий экран расходов">Расходы книги {org}</section> }));
vi.mock("./accounting-controls", () => ({ AccountingControls: ({ onChanged, initialSection }: { onChanged: () => void; initialSection: string }) => <><span>Раздел контроля: {initialSection}</span><button onClick={onChanged}>Обновить список организаций</button></> }));

import { AccountingView } from "./accounting-view";

const report = { organization_id: 1, status: "preliminary", pending_documents: 0,
  trial_balance: [{ account: "41", title: "Товары", currency: "BYN", dimensions: {}, opening: "0.00", debit: "100.00", credit: "0.00", closing: "100.00", off_balance: false }],
  movements: [{ entry_id: 5, source: "Поступление 1", date: "2026-09-01", account: "41", side: "debit", amount: "100.00" }],
  balance: { equity: "1000.00", difference: "0.00" }, pnl: { income: "180.00", expenses: "100.00", profit: "80.00" }, cashflow: { closing: "1080.00" } };
const fetchMock = vi.fn();
const respond = (data: unknown, ok = true) => Promise.resolve({ ok, json: async () => data });
function openPage(section: string, page: string) {
  fireEvent.click(screen.getByRole("button", { name: section, exact: true }));
  if (section !== page) fireEvent.click(screen.getByRole("button", { name: page, exact: true }));
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((input: string, init?: RequestInit) => {
    if (input.endsWith("/organizations")) return respond([{ id: 1, name: "Тестовая компания", unp: "999999999" }, { id: 2, name: "Вторая компания", unp: "888888888" }]);
    if (input.includes("/accounts?")) return respond([{ id: 1, code: "41", title: "Товары", cash: false, required_dimensions: [] }, { id: 2, code: "60", title: "Поставщики", cash: false, required_dimensions: [] }]);
    if (input.endsWith("/policies")) return respond([{ id: 1, effective_from: "2020-01-01", reference: "Test", normative_verified: false }]);
    if (input.includes("/reports?")) return respond(input.includes("/2/") ? { ...report, organization_id: 2, trial_balance: [], movements: [] } : report);
    if (input.endsWith("/preview")) { const body = JSON.parse(String(init?.body)); return respond({ digest: "test", explanation: body.explanation, lines: body.lines, normative_verified: false }); }
    if (input.endsWith("/entries")) return respond({ id: 6 });
    if (input.endsWith("/entries/5")) return respond({ id: 5, source: "Поступление 1", explanation: "Контрольное поступление", posting_date: "2026-09-01", lines: [{ id: 1, account_code: "41", account_title: "Товары", side: "debit", amount: "100.00" }] });
    throw new Error(input);
  });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("AccountingView", () => {
  it("uses seven sections and keeps home shortcuts in the selected section", async () => {
    render(<AccountingView />);
    await screen.findByText(/включительно: 0\./);
    const sections = screen.getByRole("navigation", { name: "Разделы бухгалтерии" });
    expect(sections.querySelectorAll("button")).toHaveLength(7);
    openPage("Зарплата", "Контроль зарплаты");
    expect(screen.getByRole("navigation", { name: "Страницы раздела Зарплата" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Рабочее место", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "Открыть: План счетов" }));
    expect(screen.getByRole("button", { name: "Закрытие месяца", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("navigation", { name: "Страницы раздела Закрытие месяца" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Закрытие месяца", exact: true }));
    expect(screen.getByText("Раздел контроля: periods")).toBeInTheDocument();
  });

  it("links the accountant report catalog to existing ledger financial reports", async () => {
    render(<AccountingView />);
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    const catalog = screen.getByRole("navigation", { name: "Отчёты бухгалтерской книги" });
    expect(catalog.querySelector('a[href="/erp/finance?tab=pnl"]')).not.toBeNull();
    expect(catalog.querySelector('a[href="/erp/finance?tab=dds"]')).not.toBeNull();
    expect(catalog.querySelector('a[href="/erp/finance?tab=balance"]')).not.toBeNull();
    expect(screen.getByText(/выберите юрлицо и период заново/)).toBeInTheDocument();
  });

  it("предвыбирает доступную книгу из org query-hint после загрузки", async () => {
    render(<AccountingView suggestedOrg="2" />);
    await screen.findByRole("option", { name: "Вторая компания · 888888888" });
    await waitFor(() => expect(screen.getByLabelText("Организация")).toHaveValue("2"));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/organizations/2/reports?"))).toBe(true);
  });

  it("не возвращает query-hint после ручного выбора и обновления списка", async () => {
    render(<AccountingView suggestedOrg="2" />);
    await waitFor(() => expect(screen.getByLabelText("Организация")).toHaveValue("2"));
    fireEvent.change(screen.getByLabelText("Организация"), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByLabelText("Организация")).toHaveValue("1"));
    openPage("Закрытие месяца", "Управление книгой");
    fireEvent.click(await screen.findByRole("button", { name: "Обновить список организаций" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/organizations"))).toHaveLength(2));
    expect(screen.getByLabelText("Организация")).toHaveValue("1");
  });

  it.each(["0", "not-an-id", "9007199254740992", "3"])("игнорирует недопустимый или недоступный org hint %s", async (suggestedOrg) => {
    render(<AccountingView suggestedOrg={suggestedOrg} />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    await waitFor(() => expect(screen.getByLabelText("Организация")).toHaveValue("1"));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/organizations/3/reports?"))).toBe(false);
  });

  it("opens an inventory_purchase source inside accounting", async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/entries/5")
      ? respond({ id: 5, operation: "inventory_purchase", source: "procurement:receipt:9", explanation: "Поступление", posting_date: "2026-09-01", lines: [] })
      : original(url, init));
    render(<AccountingView />);
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    fireEvent.click(await screen.findByText("№ 5 · Поступление 1"));
    expect(await screen.findByRole("button", { name: "Открыть поступление" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Открыть первичную накладную" })).not.toBeInTheDocument();
  });
  it("shows the saved dates, FX basis and analytics and opens the corrected entry in the same organization", async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/entries/5") ? respond({
      id: 5, source: "Correction FX", operation: "manual", explanation: "Historical snapshot", source_version: 3,
      document_date: "2026-08-28", operation_date: "2026-08-29", posting_date: "2026-09-01",
      created_at: "2026-09-02T10:11:12+03:00", rule_version: "manual-v1", correction_of: 4,
      lines: [{ id: 1, account_code: "60", account_title: "Историческое название", side: "credit", amount: "321.00",
        dimensions: { counterparty: "Поставщик A", contract: "Договор 7", lot: "Партия 9", settlement_document: "sales:document:27", bank_statement: "Выписка 9", order: "sales:document:99" }, currency: "USD",
        original_amount: "100.00", rate: "3.210000", rate_scale: 1, rate_date: "2026-08-29", rate_source: "Учебный источник", quantity: "2.000000" }],
    }) : url.endsWith("/entries/4") ? respond({ id: 4, source: "Original", explanation: "Original posting", lines: [] }) : original(url, init));
    render(<AccountingView />);
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    fireEvent.click(await screen.findByText("№ 5 · Поступление 1"));
    await screen.findByText("Historical snapshot");
    for (const value of ["2026-08-28", "2026-08-29", "2026-09-01", "2026-09-02T10:11:12+03:00", "manual-v1", "Поставщик A", "Договор 7", "Партия 9", "Количество: 2.000000", "Сумма в валюте: 100.00 USD", "Курс: 3.210000 BYN за 1 USD"]) expect(screen.getByText(value, { exact: true })).toBeInTheDocument();
    expect(screen.getByText("Дата курса: 2026-08-29 · Источник: Учебный источник")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Оригинал документа № 27" })).toHaveAttribute("href", "/api/sales/organizations/1/documents/27/original");
    expect(screen.queryByRole("link", { name: "Оригинал документа № 99" })).not.toBeInTheDocument();
    expect(screen.getByText("Банковская выписка")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Исправляет операцию № 4" }));
    expect(await screen.findByText("Original posting")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/accounting/organizations/1/entries/4")).toBe(true);
  });
  it("keeps the latest entry selection and ignores responses after closing", async () => {
    const original = fetchMock.getMockImplementation()!;
    const pending: Array<(value: unknown) => void> = [];
    fetchMock.mockImplementation((url: string, init?: RequestInit) => url.endsWith("/entries/5")
      ? new Promise((resolve) => pending.push(resolve)) : original(url, init));
    render(<AccountingView />);
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    const link = await screen.findByText("№ 5 · Поступление 1");
    fireEvent.click(link);
    fireEvent.click(link);
    const entry = (explanation: string) => ({ ok: true, json: async () => ({ id: 5, source: "Source", posting_date: "2026-09-01", explanation, lines: [] }) });
    await act(async () => pending[1](entry("Latest selection")));
    await act(async () => pending[0](entry("Stale selection")));
    expect(screen.getByText("Latest selection")).toBeInTheDocument();
    expect(screen.queryByText("Stale selection")).not.toBeInTheDocument();
    fireEvent.click(link);
    fireEvent.click(screen.getByText("Закрыть карточку"));
    await act(async () => pending[2](entry("Closed selection")));
    expect(screen.queryByRole("region", { name: "Карточка проводки" })).not.toBeInTheDocument();
  });
  it("renders preliminary reports and opens a traceable entry", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    expect(await screen.findByText("Оборотно-сальдовая ведомость")).toBeInTheDocument();
    expect(screen.getByText(/Предварительные данные/)).toBeInTheDocument();
    expect(screen.getByText("80.00 BYN")).toBeInTheDocument();
    fireEvent.click(screen.getByText("№ 5 · Поступление 1"));
    expect(await screen.findByText("Контрольное поступление")).toBeInTheDocument();
  });
  it("requires preview and explicit confirmation before posting", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    await screen.findByText("Оборотно-сальдовая ведомость");
    openPage("Документы", "Ручная операция");
    fireEvent.change(screen.getByLabelText("Основание"), { target: { value: "Справка 1" } });
    fireEvent.change(screen.getByLabelText("Содержание"), { target: { value: "Поступление материалов" } });
    fireEvent.change(screen.getByLabelText("Счёт 1"), { target: { value: "41" } });
    fireEvent.change(screen.getByLabelText("Счёт 2"), { target: { value: "60" } });
    fireEvent.change(screen.getByLabelText("Сумма 1"), { target: { value: "100.00" } });
    fireEvent.change(screen.getByLabelText("Сумма 2"), { target: { value: "100.00" } });
    expect(screen.queryByText("Подтвердить и провести")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Проверить проводки"));
    fireEvent.click(await screen.findByText("Подтвердить и провести"));
    expect(await screen.findByText("Операция № 6 проведена.")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/entries"));
    expect(JSON.parse(call?.[1].body).lines[0].amount).toBe("100.00");
  });
  it("clears the previous organization report on selection change", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    await screen.findByText(/включительно: 0\./);
    openPage("Отчёты", "ОСВ и отчёты");
    await screen.findByText("Оборотно-сальдовая ведомость");
    fireEvent.change(screen.getByLabelText("Организация"), { target: { value: "2" } });
    await waitFor(() => expect(screen.queryByText("№ 5 · Поступление 1")).not.toBeInTheDocument());
    expect(await screen.findByText("За выбранный период нет проводок.")).toBeInTheDocument();
  });
  it("keeps the in-flight accounts response after reselecting the active organization", async () => {
    const original = fetchMock.getMockImplementation()!;
    const pendingAccounts: Array<(value: unknown) => void> = [];
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/accounts?")) return new Promise((resolve) => pendingAccounts.push(resolve));
      if (url.includes("/bank-import/candidates")) return respond([{
        source_snapshot: {
          transaction_id: 9, ext_id: "BANK-9", occurred_on: "2026-09-01", amount: "100.00", currency: "BYN",
          payer_unp: "999999999", payer_name: "Плательщик", purpose: "Оплата", account_code: null, match_status: "unmatched",
        },
        source_digest: "digest-9", binding_status: "own", imported: false, entry_id: null,
      }]);
      return original(url, init);
    });

    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    await waitFor(() => expect(pendingAccounts).toHaveLength(1));

    fireEvent.change(screen.getByLabelText("Организация"), { target: { value: "1" } });
    await act(async () => pendingAccounts[0](respond([
      { id: 51, code: "51", title: "Расчётный счёт", cash: true, category: "asset", required_dimensions: [] },
      { id: 60, code: "60", title: "Расчёты с поставщиками", cash: false, category: "liability", required_dimensions: [] },
    ])));

    openPage("Банк и платежи", "Импорт выписки");
    await screen.findByText("BANK-9");
    fireEvent.click(screen.getByRole("button", { name: "Выбрать", exact: true }));

    expect(screen.getByRole("option", { name: "51 · Расчётный счёт" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "60 · Расчёты с поставщиками" })).toBeInTheDocument();
  });
  it("shows denied access without fabricated empty balances", async () => {
    fetchMock.mockImplementation(() => respond({ detail: "No access" }, false));
    render(<AccountingView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No access");
    expect(screen.queryByText("Оборотно-сальдовая ведомость")).not.toBeInTheDocument();
  });
  it("shows a safe error when the accounting API returns no JSON", async () => {
    fetchMock.mockImplementation(() => Promise.resolve({
      ok: false,
      json: async () => { throw new SyntaxError("Unexpected end of JSON input"); },
    }));
    render(<AccountingView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Бухгалтерия временно недоступна. Повторите загрузку.");
    expect(screen.queryByText(/Unexpected end of JSON input/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить список организаций" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/organizations"))).toHaveLength(2));
  });
  it("opens the production accounting workspace from the accountant navigation", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    openPage("Документы", "Производство");
    expect(await screen.findByRole("region", { name: "Источники затрат производства" })).toBeInTheDocument();
    expect(screen.getByText(/Затраты производства/)).toBeInTheDocument();
  });
  it("opens the separate verified payroll accrual workspace", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    openPage("Зарплата", "Начисления зарплаты");
    expect(await screen.findByRole("region", { name: "Проверенные начисления зарплаты" })).toBeInTheDocument();
    expect(screen.getByText(/Это не расчёт зарплаты, удержаний, взносов или обязательной отчётности/)).toBeInTheDocument();
  });
  it("links the existing HR draft from payroll without presenting it as a posting", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    openPage("Зарплата", "Черновая ведомость HR");
    expect(screen.getByRole("link", { name: "Открыть черновую ведомость HR" })).toHaveAttribute("href", "/erp/hr/payroll");
    expect(screen.getByText(/не создаёт бухгалтерские проводки/)).toBeInTheDocument();
  });
  it("opens the separate reviewed payroll statutory workspace", async () => {
    render(<AccountingView />);
    await screen.findByRole("option", { name: "Тестовая компания · 999999999" });
    openPage("Зарплата", "Удержания и взносы");
    expect(await screen.findByRole("region", { name: "Проверенные удержания и взносы" })).toBeInTheDocument();
    expect(screen.getByText(/Ставки и расчёт от оклада не угадываются/)).toBeInTheDocument();
  });
});



it("opens expense control with the selected accounting organization", async () => {
  render(<AccountingView />);
  await screen.findByRole("option", {name:"Тестовая компания · 999999999"});
  fireEvent.click(screen.getByRole("button", {name:"Открыть: Контроль расходов"}));
  expect(screen.getByText("Расходы книги 1")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Организация"), {target:{value:"2"}});
  await screen.findByText("Расходы книги 2");
});
