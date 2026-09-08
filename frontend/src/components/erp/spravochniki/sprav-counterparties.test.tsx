import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
}));

import { SpravCounterparties } from "@/components/erp/spravochniki/sprav-counterparties";

function mockResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe("SpravCounterparties", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
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
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/system/references/query",
      expect.objectContaining({
        body: JSON.stringify({ ref: "core.counterparties", name: "Ром", limit: 50 }),
      }),
    );
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

    expect(await screen.findByRole("status")).toHaveTextContent("Совпадений нет");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each([
    [401, "Сессия истекла или отсутствует авторизация (401)."],
    [403, "Доступ к справочнику контрагентов запрещён (403)."],
    [503, "Сервис справочников недоступен или вернул некорректный ответ."],
  ] as const)("различает ошибку API %s", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn(async () => mockResponse({}, status)));
    render(<SpravCounterparties initialName="Ромашка" />);

    expect(await screen.findByRole("status")).toHaveTextContent(message);
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

    expect(await screen.findByRole("status")).toHaveTextContent("Укажите только одно поле");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
