import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

import type { CounterpartyCard } from "@/lib/reference-data";

import { SpravCounterpartyEditor } from "./sprav-counterparty-editor";

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const card: CounterpartyCard = {
  id: 17,
  name: "ООО Ромашка",
  unp: "190000001",
  is_active: true,
  merged_into_id: null,
  revision: 4,
  requisites: {
    legal_address: "Старый адрес",
    registry_status: "Действующее",
    bank_name: "Старый банк",
    bank_account: "BY13NBRB36000000000000000000",
    bank_bic: "NBRBBY2X",
  },
  provenance: {},
  aliases: [],
  merged_duplicates: [],
  contacts: [{ id: 3, full_name: "Иван Петров", phone: "+375 29 111-22-33", email: "ivan@example.com", is_primary: true }],
  audit: [],
  touches: [],
  touch_summary: null,
};

const registry = {
  unp: "190000001",
  name: "ООО Новая Ромашка",
  address: "Новый адрес, 1",
  status: "Действующее",
  source: "mns_grp" as const,
  source_url: "https://grp.nalog.gov.by/api/grp-public/data?unp=190000001",
  fetched_at: "2026-09-08T12:00:00Z",
};

describe("SpravCounterpartyEditor", () => {
  beforeEach(() => {
    navigation.push.mockReset();
    navigation.refresh.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("получает preview, сохраняет только выбранные registry-поля и переходит на реальный ID с query", async () => {
    const fetchMock = vi.fn(async (input: string) =>
      input.includes("/api/integrations/egr/")
        ? response(registry)
        : response({ id: 42, revision: 1 }, 201),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <SpravCounterpartyEditor
        mode="create"
        initialUnp="190000001"
        returnQuery={{ name: "Ром", unp: "190000001" }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
    expect(await screen.findByText(/Источник: МНС \(ГРП\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать Наименование" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать УНП" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(
      "/erp/spravochniki/counterparty/42?name=%D0%A0%D0%BE%D0%BC&unp=190000001",
    ));
    expect(screen.queryByText(/Источник: МНС/)).not.toBeInTheDocument();
    fireEvent.submit(document.querySelector("form")!);
    expect(fetchMock.mock.calls.filter(([input]) => !String(input).includes("/api/integrations/egr/")).length).toBe(1);
    const saveCall = fetchMock.mock.calls.find(([input]) => !String(input).includes("/api/integrations/egr/"));
    expect(saveCall).toBeDefined();
    const saveBody = JSON.parse(String(saveCall?.[1]?.body));
    expect(saveBody).toEqual({
      registry: {
        unp: "190000001",
        fields: ["name", "unp"],
        preview: { name: "ООО Новая Ромашка", unp: "190000001" },
      },
    });
    expect(JSON.stringify(saveBody)).not.toContain("provenance");
  });

  it.each([
    [401, { detail: { message: "Нужна авторизация" } }, "Сессия истекла или отсутствует авторизация (401)."],
    [403, { detail: { message: "Недостаточно прав" } }, "Нет права изменять карточку (403)."],
    [409, { detail: { code: "duplicate_unp", message: "УНП уже занят." } }, "Найдите карточку по УНП и используйте её."],
    [409, { detail: { code: "registry_changed", message: "Предпросмотр реестра устарел." } }, "Предпросмотр реестра устарел."],
    [503, { detail: { message: "Сервис сохранения временно недоступен." } }, "Сервис сохранения временно недоступен."],
  ] as const)("ошибка сохранения %s оставляет форму и не навигирует", async (status, body, expected) => {
    const fetchMock = vi.fn(async () => response(body, status));
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="create" initialUnp="190000001" />);

    fireEvent.change(screen.getByLabelText("Наименование компании"), { target: { value: "Моя компания" } });
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Мой банк" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(expected));
    expect(screen.getByLabelText("Наименование компании")).toHaveValue("Моя компания");
    expect(screen.getByLabelText("Банк")).toHaveValue("Мой банк");
    expect(navigation.push).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ошибка lookup 503 различима, не стирает manual и не запускает auto-retry", async () => {
    const fetchMock = vi.fn(async () => response({ detail: { code: "timeout" } }, 503));
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="create" />);

    fireEvent.change(screen.getByLabelText("Наименование компании"), { target: { value: "Моя компания" } });
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Мой банк" } });
    fireEvent.change(screen.getByLabelText("УНП (карточка)"), { target: { value: "190000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Реестр МНС не ответил вовремя"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Наименование компании")).toHaveValue("Моя компания");
    expect(screen.getByLabelText("Банк")).toHaveValue("Мой банк");
    expect(navigation.push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Наименование компании")).toHaveValue("Моя компания");
    expect(screen.getByLabelText("Банк")).toHaveValue("Мой банк");
  });

  it("PATCH отправляет только изменённый банк и изменённые или новые контакты", async () => {
    const fetchMock = vi.fn(async () => response({ id: 17, revision: 5 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="edit" card={card} />);

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Новый банк" } });
    fireEvent.change(screen.getByLabelText("Телефон контакта 1"), { target: { value: "+375 29 222-33-44" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Добавить контакт" }));
    fireEvent.change(screen.getByLabelText("Имя контакта 2"), { target: { value: "Анна" } });
    fireEvent.change(screen.getByLabelText("Email контакта 2"), { target: { value: "anna@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/mdm/counterparty/17",
      expect.objectContaining({ method: "PATCH" }),
    ));
    const saveBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(saveBody.expected_revision).toBe(4);
    expect(saveBody.manual).toEqual({ bank_name: "Новый банк" });
    expect(saveBody.registry).toBeUndefined();
    expect(saveBody.contacts).toEqual([
      { id: 3, full_name: "Иван Петров", phone: "+375 29 222-33-44", email: "ivan@example.com", is_primary: true },
      { full_name: "Анна", phone: null, email: "anna@example.com", is_primary: false },
    ]);
    expect(navigation.refresh).toHaveBeenCalledTimes(1);
  });

  it("отмена сбрасывает draft и не выполняет запись", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="edit" card={card} />);

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Черновой банк" } });
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    expect(screen.getByLabelText("Банк")).toHaveValue("Старый банк");
  });

  it("не смешивает ответы preview после смены УНП", async () => {
    const pending: Array<(value: unknown) => void> = [];
    const fetchMock = vi.fn(() => new Promise((resolve) => pending.push(resolve)));
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="create" />);

    const input = screen.getByLabelText("УНП (карточка)");
    fireEvent.change(input, { target: { value: "190000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
    fireEvent.change(input, { target: { value: "190000002" } });
    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));

    pending[1](response({ ...registry, unp: "190000002", name: "Вторая компания" }));
    expect(await screen.findByText("Вторая компания")).toBeInTheDocument();
    pending[0](response({ ...registry, name: "Первая компания" }));
    await waitFor(() => expect(screen.queryByText("Первая компания")).not.toBeInTheDocument());
    expect(screen.getByText("Вторая компания")).toBeInTheDocument();
  });

  it("не даёт редактировать архивную карточку без подтверждённой версии", () => {
    render(<SpravCounterpartyEditor mode="edit" card={{ ...card, is_active: false, revision: undefined }} />);

    expect(screen.getByRole("status")).toHaveTextContent("Архивная карточка доступна только для чтения");
    expect(screen.queryByRole("button", { name: "Редактировать" })).not.toBeInTheDocument();
  });

  it("при смене ID сбрасывает редактор на новую компанию даже при той же revision", () => {
    const fetchMock = vi.fn(async () => response({ id: 18, revision: 4 }));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravCounterpartyEditor mode="edit" card={card} />);

    view.rerender(<SpravCounterpartyEditor mode="edit" card={{ ...card, id: 18, name: "Другая компания" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    expect(screen.getByLabelText("Наименование компании")).toHaveValue("Другая компания");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    return waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/mdm/counterparty/18",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"expected_revision":4') }),
    ));
  });

  it("сохраняет dirty draft и baseline revision при фоне с новой revision", async () => {
    const fetchMock = vi.fn(async () => response({ id: 17, revision: 5 }));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravCounterpartyEditor mode="edit" card={card} />);

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Мой черновик" } });
    view.rerender(<SpravCounterpartyEditor mode="edit" card={{ ...card, revision: 5, name: "Изменено снаружи" }} />);
    expect(screen.getByLabelText("Банк")).toHaveValue("Мой черновик");
    expect(screen.getByLabelText("Наименование компании")).toHaveValue("ООО Ромашка");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body.expected_revision).toBe(4);
    expect(body.manual).toEqual({ bank_name: "Мой черновик" });
  });

  it("не открывает edit до свежих props после сохранения и принимает свежий draft после refresh", async () => {
    const fetchMock = vi.fn(async () => response({ id: 17, revision: 5 }));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravCounterpartyEditor mode="edit" card={card} />);

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Сохранённый банк" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(navigation.refresh).toHaveBeenCalledTimes(1));
    const waitingButton = await screen.findByRole("button", { name: "Ожидание обновления…" });
    expect(waitingButton).toBeDisabled();
    fireEvent.click(waitingButton);
    expect(screen.queryByLabelText("Банк")).not.toBeInTheDocument();

    view.rerender(<SpravCounterpartyEditor
      mode="edit"
      card={{ ...card, revision: 5, requisites: { ...card.requisites, bank_name: "Свежий банк" } }}
    />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Редактировать" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    expect(screen.getByLabelText("Банк")).toHaveValue("Свежий банк");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ручная правка после выбора registry-поля снимает выбор и не даёт ему затереть manual", async () => {
    const fetchMock = vi.fn(async (input: string) =>
      input.includes("/api/integrations/egr/")
        ? response(registry)
        : response({ id: 42, revision: 1 }, 201),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="create" initialUnp="190000001" />);

    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
    await screen.findByText(/Источник: МНС \(ГРП\)/);
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать Наименование" }));
    fireEvent.change(screen.getByLabelText("Наименование компании"), { target: { value: "Ручное имя" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(body.manual.name).toBe("Ручное имя");
    expect(body.registry).toBeUndefined();
  });

  it("синхронный latch не допускает двойной PATCH до ответа сервера", async () => {
    let resolveSave: (value: unknown) => void = () => undefined;
    const fetchMock = vi.fn((input: string) => {
      if (input.includes("/api/system/mdm/counterparty/")) {
        return new Promise((resolve) => { resolveSave = resolve; });
      }
      return Promise.resolve(response({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterpartyEditor mode="edit" card={card} />);

    fireEvent.click(screen.getByRole("button", { name: "Редактировать" }));
    fireEvent.change(screen.getByLabelText("Банк"), { target: { value: "Новый банк" } });
    const form = document.querySelector("form");
    expect(form).not.toBeNull();
    fireEvent.submit(form!);
    fireEvent.submit(form!);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveSave(response({ id: 17, revision: 5 }));
    await waitFor(() => expect(navigation.refresh).toHaveBeenCalledTimes(1));
  });
});
