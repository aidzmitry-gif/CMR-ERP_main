import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Component, type ReactNode } from "react";

import { ModuleBoard } from "@/components/erp/module-board";

let calls: { url: string; method: string }[];

beforeEach(() => {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, opts?: { method?: string }) => {
      const method = opts?.method ?? "GET";
      calls.push({ url, method });
      if (method === "GET") {
        return { ok: true, json: async () => [{ id: 1, name: "Кампания", channel: "email", status: "new" }] };
      }
      return { ok: true, json: async () => ({}) };
    }),
  );
});
afterEach(() => vi.restoreAllMocks());

function rejectionBoard(endpoint = "/synthetic") {
  return <ModuleBoard title="Проверка" endpoint={endpoint}
    columns={[{ key: "name", label: "Название" }, { key: "status", label: "Статус" }]}
    fields={[{ key: "name", label: "Название" }]}
    statusKey="status" statusFlow={["new", "done"]} patchPath="/synthetic"
    action={{ label: "Запустить", path: "/synthetic/{id}/launch" }} />;
}

function readResponse() {
  return { ok: true, json: async () => [{ id: 1, name: "Запись", status: "new" }] };
}

function beginDraft() {
  fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
  fireEvent.change(screen.getByRole("textbox", { name: "Название" }), { target: { value: "Черновик" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
}

describe("ModuleBoard write confirmation", () => {
  it("HTTP422 сохраняет введённый черновик и не обновляет список как после успеха", async () => {
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) =>
      options?.method === "POST" ? { ok: false, status: 422 } : readResponse());
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    beginDraft();
    expect(await screen.findByRole("alert")).toHaveTextContent(/не выполнено|не сохранена/);
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Черновик");
    expect(fetcher.mock.calls.filter(([, options]) => !options?.method)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled();
  });

  it("сетевая ошибка не выдаётся за подтверждённый отказ и не стирает черновик", async () => {
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) => {
      if (options?.method === "POST") throw new TypeError("Synthetic connection lost");
      return readResponse();
    });
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    beginDraft();
    expect(await screen.findByRole("alert")).toHaveTextContent(/не подтверждён/);
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Черновик");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("пока сохранение ожидает ответа, другое действие не отправляет второй POST", async () => {
    let finish!: (value: { ok: boolean }) => void;
    const pending = new Promise<{ ok: boolean }>((resolve) => { finish = resolve; });
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/synthetic" && options?.method === "POST") return pending;
      return readResponse();
    });
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    beginDraft();
    try {
      fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
      expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
      expect(screen.getByRole("button", { name: "Запустить" })).toBeDisabled();
    } finally {
      await act(async () => { finish({ ok: true }); });
    }
  });

  it("отклонённый PATCH показывает конфликт и сохраняет прежний статус без ложного обновления", async () => {
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) =>
      options?.method === "PATCH" ? { ok: false, status: 409 } : readResponse());
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    fireEvent.click(await screen.findByRole("button", { name: "new" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Обновите список/);
    expect(screen.getByRole("button", { name: "new" })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("отказ запуска403 виден пользователю и не вызывает обновление как после успешного запуска", async () => {
    const fetcher = vi.fn(async (_url: string, options?: RequestInit) =>
      options?.method === "POST" ? { ok: false, status: 403 } : readResponse());
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    fireEvent.click(await screen.findByRole("button", { name: "Запустить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/прав/);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("ModuleBoard read context", () => {
  it("запоздалый ответ прежнего раздела не заменяет данные нового", async () => {
    let finish!: (value: ReturnType<typeof readResponse>) => void;
    const oldRead = new Promise<ReturnType<typeof readResponse>>((resolve) => { finish = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url === "/api/synthetic" ? oldRead
      : { ok: true, json: async () => [{ id: 2, name: "Новая запись", status: "new" }] }));
    const view = render(rejectionBoard());
    view.rerender(rejectionBoard("/second"));
    await screen.findByText("Новая запись");
    await act(async () => { finish(readResponse()); });
    expect(screen.queryByText("Запись")).not.toBeInTheDocument();
    expect(screen.getByText("Новая запись")).toBeInTheDocument();
  });

  it("403 при чтении скрывает строки и черновик, восстановление не возвращает прежний ввод", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(readResponse())
      .mockResolvedValueOnce({ ok: false, status: 403 }).mockResolvedValue(readResponse());
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Название" }), { target: { value: "Прежний ввод" } });
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/доступ/i);
    expect(screen.queryByText("Запись")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Название" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await screen.findByText("Запись");
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("");
  });

  it("старый успешный refresh не возвращает строки после нового отказа доступа", async () => {
    let finish!: (value: ReturnType<typeof readResponse>) => void;
    const slow = new Promise<ReturnType<typeof readResponse>>((resolve) => { finish = resolve; });
    const fetcher = vi.fn().mockResolvedValueOnce(readResponse()).mockReturnValueOnce(slow)
      .mockResolvedValueOnce({ ok: false, status: 401 });
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/доступ/i);
    await act(async () => { finish(readResponse()); });
    expect(screen.queryByText("Запись")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Добавить/ })).toBeDisabled();
  });

  it("неверная форма списка показывает ошибку загрузки без падения компонента", async () => {
    class Boundary extends Component<{ children: ReactNode }, { crashed: boolean }> {
      state = { crashed: false };
      static getDerivedStateFromError() { return { crashed: true }; }
      render() { return this.state.crashed ? <p>Компонент упал</p> : this.props.children; }
    }
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ unexpected: [] }) }));
    render(<Boundary>{rejectionBoard()}</Boundary>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/список/i);
    expect(screen.queryByText("Компонент упал")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Добавить/ })).toBeDisabled();
  });

  it("временный сбой чтения сохраняет черновик, но блокирует запись до успешного обновления", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(readResponse()).mockRejectedValueOnce(new TypeError("Synthetic offline"))
      .mockResolvedValue(readResponse());
    vi.stubGlobal("fetch", fetcher);
    render(rejectionBoard());
    await screen.findByText("Запись");
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Название" }), { target: { value: "Не потерять" } });
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/устаревшими/);
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Не потерять");
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled());
    expect(screen.getByRole("textbox", { name: "Название" })).toHaveValue("Не потерять");
    expect(fetcher.mock.calls).toHaveLength(3);
  });
});

describe("ModuleBoard", () => {
  it("грузит строки и создаёт запись (POST)", async () => {
    render(
      <ModuleBoard
        title="Маркетинг"
        endpoint="/marketing/campaigns"
        columns={[{ key: "name", label: "Кампания" }, { key: "channel", label: "Канал" }]}
        fields={[{ key: "name", label: "Кампания" }, { key: "channel", label: "Канал" }]}
      />,
    );
    expect(await screen.findByRole("cell", { name: "Кампания", exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("смена статуса по клику (PATCH)", async () => {
    render(
      <ModuleBoard
        title="Закупки"
        endpoint="/procurement/requests"
        columns={[{ key: "name", label: "Имя" }, { key: "status", label: "Статус" }]}
        fields={[{ key: "name", label: "Имя" }]}
        statusKey="status"
        statusFlow={["new", "done"]}
        patchPath="/procurement/requests"
      />,
    );
    const statusBtn = await screen.findByRole("button", { name: "new" });
    fireEvent.click(statusBtn);
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
  });

  it("кнопка действия шлёт POST, числовое поле формы редактируется", async () => {
    render(
      <ModuleBoard
        title="Маркетинг"
        endpoint="/marketing/campaigns"
        columns={[{ key: "name", label: "Имя" }]}
        fields={[{ key: "name", label: "Имя" }, { key: "leads", label: "Лиды", type: "number", default: 0 }]}
        action={{ label: "Запустить", path: "/marketing/campaigns/{id}/launch" }}
      />,
    );
    await screen.findByText("Кампания");
    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Запустить" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.url.includes("/launch"))).toBe(true),
    );
  });
});
