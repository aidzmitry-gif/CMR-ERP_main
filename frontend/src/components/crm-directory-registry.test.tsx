import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const navigation = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
vi.mock("@/lib/crm-directory", async importOriginal => ({ ...await importOriginal<typeof import("@/lib/crm-directory")>(), loadDirectory: vi.fn() }));
import { CrmDirectory } from "./crm-directory";
import { loadDirectory } from "@/lib/crm-directory";

const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const registry = { unp: "190000001", name: "Учебное юридическое лицо", address: "Учебный юридический адрес", status: "Действующее", source: "mns_grp", source_url: "https://grp.nalog.gov.by/api/grp-public/data?unp=190000001", fetched_at: "2026-10-20T12:00:00Z" };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(loadDirectory).mockResolvedValue({ status: "ok", rows: [], total: 0 });
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/integrations/egr/190000001") return json(registry);
    if (url === "/api/system/mdm/counterparty" && options?.method === "POST") return json({ id: 42, revision: 1 }, 201);
    if (url === "/api/sales/clients/owners") return json([{ id: 1, name: "Учебный менеджер" }]);
    throw new Error(`Unexpected request ${url}`);
  }));
});
afterEach(() => vi.unstubAllGlobals());

it("открывает настоящий редактор с УНП из поиска, получает preview и сохраняет только выбранные реквизиты", async () => {
  render(<CrmDirectory kind="clients" />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: " 190000001 " } });
  fireEvent.click(screen.getByRole("button", { name: "Создать по УНП" }));
  expect(screen.getByLabelText("УНП (карточка)")).toHaveValue("190000001");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
  await screen.findByText("Источник: МНС (ГРП)");
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  expect(screen.getByLabelText("Банк")).toHaveValue("");
  expect(screen.getByLabelText("Счёт IBAN")).toHaveValue("");
  for (const field of ["Юридическое наименование", "УНП", "Юридический адрес", "Статус реестра"]) fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать " + field }));
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(expect.stringContaining("/erp/spravochniki/counterparty/42")));
  const posts = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/system/mdm/counterparty");
  const payload = JSON.parse(String(posts[0][1]?.body));
  expect(payload.registry).toEqual({ unp: "190000001", fields: expect.arrayContaining(["name", "unp", "legal_address", "registry_status"]), preview: { name: registry.name, unp: registry.unp, legal_address: registry.address, registry_status: registry.status } });
  expect(payload.manual?.bank_account).toBeUndefined();
});

it("не переносит текстовый поиск в поле УНП и не запрашивает реестр при вводе", async () => {
  render(<CrmDirectory kind="clients" />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Учебный клиент" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать по УНП" }));
  expect(screen.getByLabelText("УНП (карточка)")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("УНП (карточка)"), { target: { value: "190000001" } });
  expect(fetch).not.toHaveBeenCalled();
});

it("фиксирует УНП при открытии редактора и не сбрасывает черновик из-за нового поиска", async () => {
  render(<CrmDirectory kind="clients" />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "190000001" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать по УНП" }));
  fireEvent.change(screen.getByLabelText("Юридический адрес"), { target: { value: "Адрес из черновика" } });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "190000002" } });
  expect(screen.getByLabelText("УНП (карточка)")).toHaveValue("190000001");
  expect(screen.getByLabelText("Юридический адрес")).toHaveValue("Адрес из черновика");
});

it("показывает сбой реестра без вымышленных данных или записи карточки", async () => {
  vi.mocked(fetch).mockResolvedValue(json({ detail: { code: "unconfigured" } }, 503) as Response);
  render(<CrmDirectory kind="clients" />);
  fireEvent.click(screen.getByRole("button", { name: "Создать по УНП" }));
  fireEvent.change(screen.getByLabelText("УНП (карточка)"), { target: { value: "190000001" } });
  fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
  await screen.findByText("Реестр МНС не подключён");
  expect(screen.queryByText("Учебное юридическое лицо")).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method)).toBe(false);
});

it("отмена закрывает редактор и игнорирует поздний preview без сохранения", async () => {
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; }));
  render(<CrmDirectory kind="clients" />);
  fireEvent.click(screen.getByRole("button", { name: "Создать по УНП" }));
  fireEvent.change(screen.getByLabelText("УНП (карточка)"), { target: { value: "190000001" } });
  fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
  fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
  await act(async () => finish(json(registry) as Response));
  expect(screen.getByRole("button", { name: "Создать по УНП" })).toBeInTheDocument();
  expect(screen.queryByText("Учебное юридическое лицо")).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
});

it("сохраняет отдельное создание рабочего CRM-клиента с менеджером", async () => {
  render(<CrmDirectory kind="clients" />);
  fireEvent.click(screen.getByRole("button", { name: "Новый клиент" }));
  await waitFor(() => expect(screen.getByLabelText("Ответственный")).toHaveValue("1"));
  expect(screen.getByRole("form", { name: "Новый клиент CRM" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Получить по УНП" })).not.toBeInTheDocument();
});

it("не предлагает создание по УНП в справочнике контактов", async () => {
  render(<CrmDirectory kind="contacts" />);
  await screen.findByText("Найдено: 0");
  expect(screen.queryByRole("button", { name: "Создать по УНП" })).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});
