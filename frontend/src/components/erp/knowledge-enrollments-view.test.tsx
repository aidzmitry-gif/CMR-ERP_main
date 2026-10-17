import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgeEnrollmentsView } from "@/components/erp/knowledge-enrollments-view";

// Компонент ходит напрямую в global fetch (без @/lib/api): мокаем его.
// GET /api/knowledge/enrollments?...  → отдаёт getRows
// POST /api/knowledge/enrollments     → отдаёт postResult ({ ok, status })
type Row = {
  id: number;
  course_id: number;
  employee_name: string;
  status: "assigned" | "in_progress" | "completed" | "overdue";
  progress: number;
  assigned_at: string | null;
  completed_at: string | null;
};

let getRows: Row[] = [];
let postResult: { ok: boolean; status?: number } = { ok: true, status: 200 };
let fetchMock: ReturnType<typeof vi.fn>;
let getHandler: ((url: string, opts?: RequestInit) => Promise<Response>) | null = null;
let postHandler: (() => Promise<Response>) | null = null;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function lastGetUrl(): string {
  const getCalls = fetchMock.mock.calls.filter(
    ([, opts]) => (opts as RequestInit | undefined)?.method !== "POST",
  );
  return String(getCalls[getCalls.length - 1]?.[0] ?? "");
}

beforeEach(() => {
  getRows = [];
  postResult = { ok: true, status: 200 };
  getHandler = null;
  postHandler = null;
  fetchMock = vi.fn((url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") {
      return postHandler
        ? postHandler()
        : Promise.resolve({ ok: postResult.ok, status: postResult.status ?? 200 } as Response);
    }
    return getHandler
      ? getHandler(String(url), opts)
      : Promise.resolve({ ok: true, json: async () => getRows } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

const row = (over: Partial<Row> = {}): Row => ({
  id: 1,
  course_id: 7,
  employee_name: "Иванов Иван",
  status: "assigned",
  progress: 0,
  assigned_at: "2026-07-01",
  completed_at: null,
  ...over,
});

describe("KnowledgeEnrollmentsView", () => {
  it("пустой ответ показывает строку «Назначений нет»", async () => {
    getRows = [];
    render(<KnowledgeEnrollmentsView />);
    expect(await screen.findByText("Назначений нет")).toBeInTheDocument();
  });

  it("рендерит назначения: имя, курс, прогресс и русскую подпись статуса", async () => {
    getRows = [row({ id: 1, course_id: 42, employee_name: "Петров П.П.", status: "in_progress", progress: 40 })];
    render(<KnowledgeEnrollmentsView />);

    const tr = (await screen.findByText("Петров П.П.")).closest("tr") as HTMLElement;
    expect(within(tr).getByText("42")).toBeInTheDocument();
    expect(within(tr).getByText("40%")).toBeInTheDocument();
    // status "in_progress" → человекочитаемая подпись в строке, а не сырой код
    // ("В процессе" также есть в option фильтра — потому ищем в пределах строки)
    expect(within(tr).getByText("В процессе")).toBeInTheDocument();
    expect(within(tr).queryByText("in_progress")).not.toBeInTheDocument();
  });

  it("null-даты в строке отображаются как «—»", async () => {
    getRows = [row({ employee_name: "Сидоров С.С.", assigned_at: null, completed_at: null })];
    render(<KnowledgeEnrollmentsView />);

    const cell = await screen.findByText("Сидоров С.С.");
    const tr = cell.closest("tr") as HTMLElement;
    // назначен и завершён — оба null → две прочерк-ячейки в этой же строке
    expect(within(tr).getAllByText("—")).toHaveLength(2);
  });

  it("выбор статуса в фильтре перезапрашивает список с параметром status", async () => {
    getRows = [row()];
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Иванов Иван");

    const before = fetchMock.mock.calls.length;
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "completed" } });

    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before));
    expect(lastGetUrl()).toContain("status=completed");
  });

  it("ввод сотрудника в фильтр уходит в запрос как employee_name", async () => {
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");

    fireEvent.change(screen.getByPlaceholderText("Фильтр по сотруднику"), {
      target: { value: "Кузнецов" },
    });

    await waitFor(() => expect(lastGetUrl()).toContain("employee_name=%D0%9A"));
    expect(decodeURIComponent(lastGetUrl())).toContain("employee_name=Кузнецов");
  });

  it("кнопка «+ Назначить курс» раскрывает форму и меняет подпись на «Отмена»", async () => {
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");

    expect(screen.queryByText("Назначение курса сотруднику")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "+ Назначить курс" });
    fireEvent.click(toggle);

    expect(screen.getByText("Назначение курса сотруднику")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();
  });

  it("успешное создание шлёт POST с course_id/employee_name и перезагружает список", async () => {
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");

    fireEvent.click(screen.getByRole("button", { name: "+ Назначить курс" }));
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Иванов Иван"), {
      target: { value: "Новиков Н.Н." },
    });
    // после POST список вернёт уже нового сотрудника
    getRows = [row({ id: 9, course_id: 5, employee_name: "Новиков Н.Н." })];

    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([, o]) => (o as RequestInit)?.method === "POST");
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toMatchObject({
        course_id: 5,
        employee_name: "Новиков Н.Н.",
      });
    });
    // форма закрылась (перезагрузка прошла), новый сотрудник виден в таблице
    expect(await screen.findByText("Новиков Н.Н.")).toBeInTheDocument();
    expect(screen.queryByText("Назначение курса сотруднику")).not.toBeInTheDocument();
  });

  it("ошибка сервера при создании показывает «Ошибка N» и оставляет форму открытой", async () => {
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");

    fireEvent.click(screen.getByRole("button", { name: "+ Назначить курс" }));
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "3" } });
    fireEvent.change(screen.getByPlaceholderText("Иванов Иван"), {
      target: { value: "Ошибочный" },
    });
    postResult = { ok: false, status: 422 };

    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));

    expect(await screen.findByText("Ошибка 422")).toBeInTheDocument();
    // форма не закрылась — данные не потеряны
    expect(screen.getByText("Назначение курса сотруднику")).toBeInTheDocument();
  });

  it("GET 503 показывает отдельную ошибку списка, а не успешное пустое состояние", async () => {
    getHandler = async () => ({ ok: false, status: 503 } as Response);
    render(<KnowledgeEnrollmentsView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка 503");
    expect(screen.getByText("Не удалось загрузить назначения")).toBeInTheDocument();
    expect(screen.queryByText("Назначений нет")).not.toBeInTheDocument();
    expect(screen.getByText("Ошибка 503").closest("form")).toBeNull();
  });

  it("сетевая ошибка списка повторяется с текущими фильтрами и может завершиться успехом", async () => {
    let filteredCalls = 0;
    getHandler = async (url) => {
      if (!url.includes("status=in_progress")) return { ok: true, json: async () => [] } as Response;
      filteredCalls += 1;
      if (filteredCalls === 1) throw new TypeError("Failed to fetch");
      return { ok: true, json: async () => [row({ employee_name: "Retry", status: "in_progress" })] } as Response;
    };
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "in_progress" } });

    expect(await screen.findByRole("alert")).toHaveTextContent("Ошибка сети");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Retry")).toBeInTheDocument();
    expect(decodeURIComponent(lastGetUrl())).toContain("status=in_progress");
  });

  it("сбой обновления оставляет назначения тех же фильтров и явно помечает данные устаревшими", async () => {
    let calls = 0;
    getHandler = async () => {
      calls += 1;
      return calls === 1
        ? ({ ok: true, json: async () => [row()] } as Response)
        : ({ ok: false, status: 503 } as Response);
    };
    render(<KnowledgeEnrollmentsView />);
    expect(await screen.findByText("Иванов Иван")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Назначить курс" }));
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Иванов Иван"), { target: { value: "Петров П.П." } });
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Показаны ранее загруженные данные");
    expect(screen.getByText("Иванов Иван")).toBeInTheDocument();
    expect(screen.queryByText("Назначений нет")).not.toBeInTheDocument();
  });

  it("при смене фильтра очищает предыдущие назначения, пока загружается новый список", async () => {
    const pending = deferred<Response>();
    let calls = 0;
    getHandler = () => (++calls === 1
      ? Promise.resolve({ ok: true, json: async () => [row()] } as Response)
      : pending.promise);
    render(<KnowledgeEnrollmentsView />);
    expect(await screen.findByText("Иванов Иван")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Фильтр по сотруднику"), { target: { value: "Петров" } });
    expect(screen.queryByText("Иванов Иван")).not.toBeInTheDocument();
    expect(screen.getByText("Загрузка списка…")).toBeInTheDocument();
    expect(screen.queryByText("Назначений нет")).not.toBeInTheDocument();
  });

  it("поздний ответ предыдущего фильтра не перезаписывает текущий, даже если mock игнорирует abort", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    let calls = 0;
    getHandler = () => (++calls === 1 ? first.promise : second.promise);
    render(<KnowledgeEnrollmentsView />);
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(1));
    const firstSignal = fetchMock.mock.calls[0][1]?.signal;

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "completed" } });
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(2));
    expect(firstSignal?.aborted).toBe(true);
    second.resolve({ ok: true, json: async () => [row({ employee_name: "Current", status: "completed" })] } as Response);
    expect(await screen.findByText("Current")).toBeInTheDocument();

    await act(async () => {
      first.resolve({ ok: true, json: async () => [row({ employee_name: "Old" })] } as Response);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.queryByText("Old")).not.toBeInTheDocument();
  });

  it("размонтирование отменяет GET и поздний ответ не создаёт ошибку или новый запрос", async () => {
    const pending = deferred<Response>();
    getHandler = () => pending.promise;
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const view = render(<KnowledgeEnrollmentsView />);
    await waitFor(() => expect(fetchMock.mock.calls).toHaveLength(1));
    const signal = fetchMock.mock.calls[0][1]?.signal;

    view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve({ ok: false, status: 503 } as Response);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(view.container.querySelector('[role="alert"]')).toBeNull();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it("успех POST после смены фильтра перезагружает текущий фильтр, а не захваченный", async () => {
    const pendingPost = deferred<Response>();
    postHandler = () => pendingPost.promise;
    render(<KnowledgeEnrollmentsView />);
    await screen.findByText("Назначений нет");
    const employeeFilter = screen.getByPlaceholderText("Фильтр по сотруднику");
    fireEvent.change(employeeFilter, { target: { value: "Сидоров" } });
    await waitFor(() => expect(decodeURIComponent(lastGetUrl())).toContain("employee_name=Сидоров"));

    fireEvent.click(screen.getByRole("button", { name: "+ Назначить курс" }));
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "5" } });
    fireEvent.change(screen.getByPlaceholderText("Иванов Иван"), { target: { value: "Новиков Н.Н." } });
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, opts]) => opts?.method === "POST")).toBe(true));

    fireEvent.change(employeeFilter, { target: { value: "Петров" } });
    await waitFor(() => expect(decodeURIComponent(lastGetUrl())).toContain("employee_name=Петров"));
    const beforePostComplete = fetchMock.mock.calls.filter(([, opts]) => opts?.method !== "POST").length;
    pendingPost.resolve({ ok: true, status: 201 } as Response);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, opts]) => opts?.method !== "POST").length).toBe(beforePostComplete + 1));
    expect(decodeURIComponent(lastGetUrl())).toContain("employee_name=Петров");
    expect(decodeURIComponent(lastGetUrl())).not.toContain("employee_name=Сидоров");
  });
});
