import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HrOkkView } from "@/components/erp/hr-okk-view";

// Компонент ходит в backend напрямую через global fetch (не через @/lib/api),
// поэтому мокаем fetch и раздаём ответы по URL.
type OkkScore = {
  id: number;
  employee_id: number;
  period: string;
  discipline: number;
  quality: number;
  service: number;
  teamwork: number;
  total: number;
  comment: string;
};

const employees = [
  { id: 1, full_name: "Иванов Иван", position: "Менеджер" },
  { id: 2, full_name: "Петрова Анна", position: "Оператор" },
];

const scoreRow: OkkScore = {
  id: 10,
  employee_id: 1,
  period: "2026-06",
  discipline: 24,
  quality: 23,
  service: 22,
  teamwork: 25,
  total: 94,
  comment: "Отличный месяц",
};

function jsonResponse(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(data),
  } as Response);
}

// Настраиваемый роутер fetch: тест задаёт ответы для scores/employees/post.
function installFetch(opts: {
  scores?: unknown;
  scoresOk?: boolean;
  employees?: unknown;
  onPost?: (body: unknown) => Promise<Response>;
}) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    if (u.startsWith("/api/hr/employees")) {
      return jsonResponse(opts.employees ?? employees);
    }
    if (u.startsWith("/api/hr/okk-scores")) {
      if (init?.method === "POST") {
        const body = init.body ? JSON.parse(String(init.body)) : {};
        return opts.onPost ? opts.onPost(body) : jsonResponse({ ...scoreRow, id: 11 });
      }
      return jsonResponse(opts.scores ?? [], opts.scoresOk ?? true, opts.scoresOk === false ? 500 : 200);
    }
    return jsonResponse({}, false, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("HrOkkView", () => {
  it("рендерит заголовок ОКК и подсказку по категориям", async () => {
    installFetch({ scores: [] });
    render(<HrOkkView />);
    expect(screen.getByText("ОКК · Оценки сотрудников")).toBeInTheDocument();
    expect(screen.getByText(/дисциплина, качество, сервис, командная работа/)).toBeInTheDocument();
    // дождаться завершения загрузки, чтобы не ловить act-варнинги
    await waitFor(() => expect(screen.getByText("Оценок ОКК пока нет.")).toBeInTheDocument());
  });

  it("пустой ответ показывает «Оценок ОКК пока нет.»", async () => {
    installFetch({ scores: [] });
    render(<HrOkkView />);
    expect(await screen.findByText("Оценок ОКК пока нет.")).toBeInTheDocument();
  });

  it("данные рендерятся строкой таблицы с именем сотрудника, баллами и итогом", async () => {
    installFetch({ scores: [scoreRow] });
    render(<HrOkkView />);
    // имя резолвится через справочник сотрудников (employee_id → full_name)
    expect(await screen.findByText("Иванов Иван")).toBeInTheDocument();
    const row = screen.getByText("Иванов Иван").closest("tr") as HTMLElement;
    expect(within(row).getByText("2026-06")).toBeInTheDocument();
    expect(within(row).getByText("24")).toBeInTheDocument(); // дисциплина
    expect(within(row).getByText("94")).toBeInTheDocument(); // итого-бейдж
    expect(within(row).getByText("Отличный месяц")).toBeInTheDocument();
  });

  it("ошибка загрузки показывает сообщение о сбое HR-модуля", async () => {
    installFetch({ scoresOk: false });
    render(<HrOkkView />);
    expect(
      await screen.findByText(/Не удалось загрузить оценки ОКК/),
    ).toBeInTheDocument();
    // таблицы при ошибке нет
    expect(screen.queryByText("Оценок ОКК пока нет.")).not.toBeInTheDocument();
  });

  it("кнопка «+ Добавить оценку» открывает форму новой оценки", async () => {
    installFetch({ scores: [] });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    expect(screen.queryByText("Новая оценка ОКК")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));
    expect(screen.getByText("Новая оценка ОКК")).toBeInTheDocument();
    // селект сотрудников наполнен из справочника
    expect(screen.getByRole("option", { name: /Иванов Иван · Менеджер/ })).toBeInTheDocument();
  });

  it("итоговый бейдж в форме суммирует 4 категории вживую", async () => {
    installFetch({ scores: [] });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));

    const disc = screen.getByLabelText(/Дисциплина/);
    const qual = screen.getByLabelText(/Качество/);
    fireEvent.change(disc, { target: { value: "20" } });
    fireEvent.change(qual, { target: { value: "15" } });

    // итоговый бейдж формы: 20 + 15 = 35 (значение уникально на экране)
    expect(screen.getByText("35")).toBeInTheDocument();
  });

  it("ScoreInput ограничивает значение сверху 25", async () => {
    installFetch({ scores: [] });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));

    const disc = screen.getByLabelText(/Дисциплина/) as HTMLInputElement;
    fireEvent.change(disc, { target: { value: "99" } });
    expect(disc.value).toBe("25"); // зажато до максимума
  });

  it("сабмит без выбранного сотрудника показывает ошибку валидации, POST не уходит", async () => {
    const fetchMock = installFetch({ scores: [] });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Укажите сотрудника и период")).toBeInTheDocument();
    // POST-запрос не отправлялся
    expect(
      fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST"),
    ).toBe(false);
  });

  it("успешный сабмит шлёт POST с телом оценки и закрывает форму", async () => {
    let posted: unknown = null;
    const fetchMock = installFetch({
      scores: [],
      onPost: (body) => {
        posted = body;
        return jsonResponse({ ...scoreRow, id: 12 });
      },
    });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));

    fireEvent.change(screen.getByLabelText("Сотрудник"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/Дисциплина/), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/Комментарий/), { target: { value: "ок" } });

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST"),
      ).toBe(true),
    );
    expect(posted).toMatchObject({ employee_id: 1, discipline: 10, comment: "ок" });
    // форма закрылась после успеха
    await waitFor(() => expect(screen.queryByText("Новая оценка ОКК")).not.toBeInTheDocument());
  });

  it("ошибка POST (detail с сервера) остаётся в форме и показывает текст ошибки", async () => {
    installFetch({
      scores: [],
      onPost: () => jsonResponse({ detail: "Оценка за период уже есть" }, false, 409),
    });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");
    fireEvent.click(screen.getByRole("button", { name: /Добавить оценку/ }));

    fireEvent.change(screen.getByLabelText("Сотрудник"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Оценка за период уже есть")).toBeInTheDocument();
    // форма НЕ закрылась — ошибку видно
    expect(screen.getByText("Новая оценка ОКК")).toBeInTheDocument();
  });

  it("фильтр по периоду добавляет query-параметр в запрос и показывает кнопку «Сбросить»", async () => {
    const fetchMock = installFetch({ scores: [] });
    render(<HrOkkView />);
    await screen.findByText("Оценок ОКК пока нет.");

    const monthInput = document.querySelector('input[type="month"]') as HTMLInputElement;
    fireEvent.change(monthInput, { target: { value: "2026-06" } });

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u]) =>
          String(u).includes("/api/hr/okk-scores?period=2026-06"),
        ),
      ).toBe(true),
    );
    expect(screen.getByRole("button", { name: "Сбросить" })).toBeInTheDocument();
  });
});
