import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function lastGetUrl(): string {
  const getCalls = fetchMock.mock.calls.filter(
    ([, opts]) => (opts as RequestInit | undefined)?.method !== "POST",
  );
  return String(getCalls[getCalls.length - 1]?.[0] ?? "");
}

beforeEach(() => {
  getRows = [];
  postResult = { ok: true, status: 200 };
  fetchMock = vi.fn((url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") {
      return Promise.resolve({ ok: postResult.ok, status: postResult.status ?? 200 });
    }
    return Promise.resolve({ ok: true, json: async () => getRows });
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
});
