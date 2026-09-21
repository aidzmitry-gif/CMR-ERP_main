import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AccountingChart } from "./accounting-chart";

const fetchMock = vi.fn();
const respond = (data: unknown, ok = true) => Promise.resolve({ ok, json: async () => data });
let adoptionRows: Record<string, unknown[]>;
let adoptionPost: ((url: string, init?: RequestInit) => Promise<unknown>) | null;
const adoption = (organizationId: number, requestKey = "00000000-0000-4000-8000-000000000001") => ({
  catalog_adoption_id: organizationId, organization_id: organizationId, effective_from: "2026-01-01",
  evidence: "Synthetic accountant catalogue adoption evidence", catalog_version: "current-chart",
  catalog_source: "https://example.test/catalog", catalog_review_state: { status: "review-required" },
  current_normative_verified: false, request_key: requestKey, digest: "a".repeat(64), actor: "tester",
});
beforeEach(() => {
  adoptionRows = {};
  adoptionPost = null;
  vi.stubGlobal("crypto", { randomUUID: () => "00000000-0000-4000-8000-000000000099" });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/catalog")) return respond({ version: "current-chart", source: "https://www.minfin.gov.by/upload/accounting/acts/postmf_290611_50.pdf", verified_through: "2026-01-01", current_normative_verified: false, chart_codes_verified: true, normative_review: { status: "chart_verified_instruction_requires_primary_review", checked_at: "2026-09-20", verified_through: "2026-01-01" }, known_amendments: [{ document: "Постановление Минфина № 126", date: "2025-10-31", effective_from: "2026-01-01", status: "chart_appendix_verified_instruction_primary_review_pending", impact_on_chart: "no_chart_code_change", chart_appendix_verified: true, full_text_verified: false, checked_at: "2026-09-20", evidence: "Текущая редакция включает № 126 и у приложения 1 перечисляет только изменения 2012 и 2013 годов." }], accounts: [{ code: "41", title: "Товары", parent: null }, { code: "41.1", title: "Товары на складах", parent: "41" }] });
    if (url.endsWith("/organizations")) return respond([{ id: 1, name: "Первая книга", unp: "999999999" }, { id: 2, name: "Вторая книга", unp: "888888888" }]);
    if (url.includes("/catalog-adoptions")) return init?.method === "POST" && adoptionPost ? adoptionPost(url, init) : respond(adoptionRows[url.includes("/2/") ? "2" : "1"] ?? []);
    if (url.includes("/accounts?")) return respond(url.includes("/2/") ? [] : [{ code: "41.1", title: "Рабочие товары", valid_from: "2026-01-01", required_dimensions: ["warehouse", "sku"], quantity_tracking: true }]);
    return respond([]);
  });
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("shows a searchable current chart without implying instruction certification", async () => {
  render(<AccountingChart />);
  await screen.findByText("Товары на складах");
  expect(screen.getByText(/Номера счетов и субсчета приложения 1 сверены/)).toBeInTheDocument();
  expect(screen.getByText(/Проверка сведений: 2026-09-20/)).toBeInTheDocument();
  expect(screen.getByText(/номера счетов и субсчета в проверенном тексте не изменены/)).toBeInTheDocument();
  expect(screen.getByText(/Приложение 1 сверено в текущей консолидированной редакции/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Поиск счетов"), { target: { value: "41.1" } });
  expect(screen.queryByText("Товары", { exact: true })).not.toBeInTheDocument();
  expect(screen.getByText("Субсчёт")).toBeInTheDocument();
});

it("separates organization working accounts with historical date and analytics", async () => {
  render(<AccountingChart />);
  await screen.findByText("Товары на складах");
  fireEvent.click(screen.getByText("Рабочий план", { exact: true }));
  expect(await screen.findByText("Рабочие товары")).toBeInTheDocument();
  expect(screen.getByText("Склад · Номенклатура")).toBeInTheDocument();
  expect(screen.getByText("Количественный")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Юридическое лицо"), { target: { value: "2" } });
  expect(screen.queryByText("Рабочие товары")).not.toBeInTheDocument();
  await screen.findByText("Рабочие счета на эту дату не настроены.");
  fireEvent.change(screen.getByLabelText("Дата рабочего плана"), { target: { value: "2025-12-31" } });
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes("/2/accounts?on=2025-12-31"))).toBe(true));
});

it("isolates catalog adoptions by organization and selected date, including empty and uncertified states", async () => {
  adoptionRows = { "1": [adoption(1)] };
  render(<AccountingChart />);
  await screen.findByText("Товары на складах");
  fireEvent.click(screen.getByText("Рабочий план", { exact: true }));
  expect(await screen.findByText(/Регламентированная готовность не подтверждена/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => url.includes("/1/catalog-adoptions"))).toBe(true);
  fireEvent.change(screen.getByLabelText("Дата рабочего плана"), { target: { value: "2025-12-31" } });
  expect(await screen.findByText(/На выбранную дату подтверждение нормативного каталога не найдено/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Юридическое лицо"), { target: { value: "2" } });
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url.includes("/2/catalog-adoptions"))).toBe(true));
  expect(await screen.findByText(/На выбранную дату подтверждение нормативного каталога не найдено/)).toBeInTheDocument();
});

it("submits only explicit adoption data and shows the server-confirmed uncertified result", async () => {
  const posts: Record<string, unknown>[] = [];
  adoptionPost = async (_url, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, string>;
    posts.push(body);
    return respond({ ...adoption(1, body.request_key), effective_from: body.effective_from, evidence: body.evidence });
  };
  render(<AccountingChart />);
  await screen.findByText("Товары на складах");
  fireEvent.click(screen.getByText("Рабочий план", { exact: true }));
  await screen.findByText(/подтверждение нормативного каталога не найдено/i);
  fireEvent.change(screen.getByLabelText("Дата рабочего плана"), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("Дата подтверждения каталога"), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("Evidence подтверждения каталога"), { target: { value: "Явное evidence бухгалтера" } });
  fireEvent.click(screen.getByText("Принять редакцию каталога"));
  expect(await screen.findByText("Подтверждение каталога сохранено сервером.")).toBeInTheDocument();
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({ effective_from: "2026-10-01", evidence: "Явное evidence бухгалтера" });
  expect(Object.keys(posts[0])).toEqual(["request_key", "effective_from", "evidence"]);
  expect(screen.getByText(/Регламентированная готовность не подтверждена/)).toBeInTheDocument();
});

it("retries one frozen adoption body after an unknown POST result", async () => {
  const posts: string[] = [];
  adoptionPost = async (_url, init) => {
    posts.push(String(init?.body));
    if (posts.length === 1) throw new Error("network lost");
    const body = JSON.parse(posts[0]) as { request_key: string };
    return respond({ ...adoption(1, body.request_key), effective_from: "2026-10-01", evidence: "Явное evidence для повторного запроса" });
  };
  render(<AccountingChart />);
  await screen.findByText("Товары на складах");
  fireEvent.click(screen.getByText("Рабочий план", { exact: true }));
  await screen.findByText(/подтверждение нормативного каталога не найдено/i);
  fireEvent.change(screen.getByLabelText("Дата рабочего плана"), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("Дата подтверждения каталога"), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText("Evidence подтверждения каталога"), { target: { value: "Явное evidence для повторного запроса" } });
  fireEvent.click(screen.getByText("Принять редакцию каталога"));
  expect(await screen.findByRole("alert")).toHaveTextContent(/Статус принятия неизвестен/);
  fireEvent.click(screen.getByText("Повторить принятие каталога"));
  expect(await screen.findByText("Подтверждение каталога сохранено сервером.")).toBeInTheDocument();
  expect(posts).toHaveLength(2);
  expect(posts[1]).toBe(posts[0]);
});
