import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

import { SpravCounterparties } from "@/components/erp/spravochniki/sprav-counterparties";

function mockResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe("SpravCounterparties", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
    navigation.push.mockReset();
    navigation.refresh.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("не запрашивает полный список на пустом вводе и подсказывает поисковый запрос", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<SpravCounterparties />);

    expect(screen.getByRole("status")).toHaveTextContent("Введите название или УНП");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ищет по названию, обновляет URL и показывает реальные ID", async () => {
    const fetchMock = vi.fn(async () =>
      mockResponse({ result: [{ id: 17, name: "ООО Ромашка", unp: "190000001" }] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterparties />);

    fireEvent.change(screen.getByLabelText("Название"), { target: { value: "Ром" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));

    expect(navigation.replace).toHaveBeenCalledWith(
      "/erp/spravochniki/counterparty?name=%D0%A0%D0%BE%D0%BC",
      { scroll: false },
    );
    expect(await screen.findByText("ООО Ромашка")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "17" })).toHaveAttribute(
      "href",
      "/erp/spravochniki/counterparty/17?name=%D0%A0%D0%BE%D0%BC",
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/references/query",
      expect.objectContaining({
        body: JSON.stringify({ ref: "core.counterparties", name: "Ром", limit: 50 }),
      }),
    );
  });

  it("создаёт из списка, сохраняет реальные registry-поля и возвращает только отправленный query", async () => {
    const registry = {
      unp: "190000001",
      name: "ООО Новая Ромашка",
      address: "Новый адрес, 1",
      status: "Действующее",
      source: "mns_grp",
      source_url: "https://grp.nalog.gov.by/api/grp-public/data?unp=190000001",
      fetched_at: "2026-09-08T12:00:00Z",
    };
    const fetchMock = vi.fn(async (input: string) => {
      if (input === "/api/system/references/query") {
        return mockResponse({ result: [{ id: 17, name: "ООО Ромашка", unp: "190000001" }] });
      }
      if (input.includes("/api/integrations/egr/")) return mockResponse(registry);
      return mockResponse({ id: 42, revision: 1 }, 201);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterparties initialName="Ром" />);

    expect(await screen.findByText("ООО Ромашка")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ Новый контрагент" }));
    expect(screen.queryByRole("button", { name: "Скрыть создание" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("УНП (карточка)"), { target: { value: "190000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Получить по УНП" }));
    expect(await screen.findByText(/Источник: МНС \(ГРП\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать Наименование" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Выбрать УНП" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(
      "/erp/spravochniki/counterparty/42?name=%D0%A0%D0%BE%D0%BC",
    ));
    const saveCall = fetchMock.mock.calls.find(([input]) => String(input) === "/api/system/mdm/counterparty");
    expect(saveCall).toBeDefined();
    expect(JSON.parse(String(saveCall?.[1]?.body))).toEqual({
      registry: {
        unp: "190000001",
        fields: ["name", "unp"],
        preview: { name: "ООО Новая Ромашка", unp: "190000001" },
      },
    });
  });

  it("не дублирует запрос при возврате тех же URL params и восстанавливает поле при новом URL", async () => {
    const fetchMock = vi.fn(async () =>
      mockResponse({ result: [{ id: 17, name: "ООО Ромашка", unp: "190000001" }] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SpravCounterparties />);

    fireEvent.change(screen.getByLabelText("Название"), { target: { value: "Ром" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    await screen.findByText("ООО Ромашка");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    view.rerender(<SpravCounterparties initialName="Ром" />);
    await waitFor(() => expect(screen.getByLabelText("Название")).toHaveValue("Ром"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    view.rerender(<SpravCounterparties initialName="Ромашка" />);
    await waitFor(() => expect(screen.getByLabelText("Название")).toHaveValue("Ромашка"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("показывает отдельное состояние отсутствия совпадений", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({ result: [] })));
    render(<SpravCounterparties initialUnp="190000001" />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Совпадений нет"),
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each([
    [401, "Сессия истекла или отсутствует авторизация (401)."],
    [403, "Доступ к справочнику контрагентов запрещён (403)."],
    [503, "Сервис справочников недоступен или вернул некорректный ответ."],
  ] as const)("различает ошибку API %s", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({}, status)));
    render(<SpravCounterparties initialName="Ромашка" />);

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(message),
    );
    expect(screen.queryByText("Совпадений нет")).not.toBeInTheDocument();
  });

  it("не позволяет второму ответу быть перезаписанным запоздалым первым ответом", async () => {
    const responses: Array<(response: unknown) => void> = [];
    const fetchMock = vi.fn(
      () => new Promise((resolve) => responses.push(resolve)),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterparties />);

    const input = screen.getByLabelText("Название");
    fireEvent.change(input, { target: { value: "Первый" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    fireEvent.change(input, { target: { value: "Второй" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));
    expect(fetchMock).toHaveBeenCalledTimes(2);

    responses[1](mockResponse({ result: [{ id: 2, name: "Второй ответ", unp: "2" }] }));
    expect(await screen.findByText("Второй ответ")).toBeInTheDocument();
    responses[0](mockResponse({ result: [{ id: 1, name: "Первый ответ", unp: "1" }] }));

    await waitFor(() => {
      expect(screen.queryByText("Первый ответ")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Второй ответ").closest("tr")).toHaveTextContent("2");
  });

  it("не принимает одновременные название и УНП", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SpravCounterparties />);

    fireEvent.change(screen.getByLabelText("Название"), { target: { value: "Ромашка" } });
    fireEvent.change(screen.getByLabelText("УНП"), { target: { value: "190000001" } });
    fireEvent.click(screen.getByRole("button", { name: "Найти" }));

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Укажите только одно поле"),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
