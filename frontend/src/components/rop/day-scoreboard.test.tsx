import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DayScoreboard } from "@/components/rop/day-scoreboard";

// Компонент ходит в бэк напрямую через глобальный fetch (не @/lib/api) — чтобы различать
// «ошибка» и «пусто». Мокаем именно fetch, formatByn/Intl (чистые хелперы) НЕ трогаем.
type Row = {
  key: string;
  title: string;
  target: number;
  actual: number;
  percent: number;
  unit: string;
};

const ROWS: Row[] = [
  { key: "calls", title: "Звонки", target: 20, actual: 25, percent: 125, unit: "count" }, // закрыт (>=100)
  { key: "meetings", title: "Встречи", target: 10, actual: 4, percent: 40, unit: "count" },
  { key: "revenue", title: "Выручка", target: 5000, actual: 2500, percent: 50, unit: "money" },
];

function okJson(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data } as Response);
}
function failStatus(status: number) {
  return Promise.resolve({ ok: false, status, json: async () => [] } as unknown as Response);
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  // по умолчанию KPI отдаёт ROWS, POST активностей — ok
  fetchMock.mockImplementation((url: string) =>
    typeof url === "string" && url.includes("/api/sales/kpis") ? okJson(ROWS) : okJson({ ok: true, date: "2026-10-30" }),
  );
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("DayScoreboard", () => {
  it("грузит показатели за день и рендерит строки с планом/фактом и процентом", async () => {
    render(<DayScoreboard />);
    // первый маунт грузит период "day"
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/sales/kpis?period=day"),
        expect.objectContaining({ cache: "no-store" }),
      ),
    );
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    expect(screen.getByText("Встречи")).toBeInTheDocument();
    expect(screen.getByText("Выручка")).toBeInTheDocument();
    // проценты выведены как есть, из процента считается тон
    expect(screen.getByText("125%")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    // счётный факт — числом; done/total в подписи (1 из 3 закрыто)
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText(/1\/3 закрыто/)).toBeInTheDocument();
  });

  it("деньги форматируются в BYN, счётные — без валюты", async () => {
    render(<DayScoreboard />);
    await screen.findByText("Выручка");
    // money-строка даёт факт и план в BYN (два вхождения), счётные — нет
    const byn = screen.getAllByText(/BYN/);
    expect(byn.length).toBeGreaterThanOrEqual(2);
  });

  it("тон по проценту: >=90 emerald, <50 red", async () => {
    render(<DayScoreboard />);
    const done = await screen.findByText("125%");
    const low = screen.getByText("40%");
    expect(done.className).toMatch(/emerald/);
    expect(low.className).toMatch(/red/);
  });

  it("кнопка «+1» есть у счётных метрик и отсутствует у денежной", async () => {
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    // две счётные (Звонки, Встречи) → две кнопки; денежная (Выручка) — без «+1»
    expect(screen.getAllByRole("button", { name: "+1" })).toHaveLength(2);
  });

  it("«+1» шлёт POST активности с ключом метрики и перечитывает показатели", async () => {
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fetchMock.mockClear();

    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([url]) => typeof url === "string" && url.includes("/api/sales/activities"),
      );
      expect(post).toBeTruthy();
      expect(post?.[1]).toMatchObject({ method: "POST" });
      expect(JSON.parse((post?.[1] as RequestInit).body as string)).toMatchObject({
        kpi_key: "calls",
        value: 1,
      });
    });
    // после отметки — повторная загрузка KPI
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => typeof url === "string" && url.includes("/api/sales/kpis")),
      ).toBe(true),
    );
  });

  it("переключение периода перечитывает показатели за выбранный период", async () => {
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fetchMock.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("period=week"),
        expect.anything(),
      ),
    );
  });

  it("honest-empty: план не задан (пусто) — подсказка завести цели, а не «ошибка»", async () => {
    fetchMock.mockImplementation(() => okJson([]));
    render(<DayScoreboard />);
    expect(await screen.findByText(/Плановые показатели не заданы/)).toBeInTheDocument();
    expect(screen.queryByText(/Не удалось загрузить/)).not.toBeInTheDocument();
    // без строк — подпись без счётчика закрытых
    expect(screen.getByText(/показатели · валюта BYN/)).toBeInTheDocument();
  });

  it("ошибка загрузки показывает повтор; клик «Повторить» перечитывает и рендерит данные", async () => {
    // первый заход — 500, после «Повторить» — успех
    fetchMock.mockImplementationOnce(() => failStatus(500));
    render(<DayScoreboard />);

    expect(await screen.findByText(/Не удалось загрузить показатели/)).toBeInTheDocument();
    // данных ещё нет
    expect(screen.queryByText("Звонки")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));

    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    expect(screen.queryByText(/Не удалось загрузить показатели/)).not.toBeInTheDocument();
  });

  it("состояние загрузки показывает скелетоны до ответа сети", async () => {
    // fetch «зависает» — статус остаётся loading
    fetchMock.mockImplementation(() => new Promise(() => {}));
    render(<DayScoreboard />);
    expect(screen.getAllByText("загрузка")).toHaveLength(6);
    expect(screen.queryByText("Звонки")).not.toBeInTheDocument();
  });
});

function posts() {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"));
}
function reads() {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/kpis"));
}
function activityResponse(status: number, body: unknown = { ok: true, date: "2026-10-30" }) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response);
}

describe("DayScoreboard confirmed write outcome", () => {
  it.each([401, 403])("protects rows on refused activity %i without treating it as success", async (code) => {
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : activityResponse(code));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent(code === 401 ? "Сессия истекла" : "Нет доступа");
    expect(screen.queryByText("Звонки")).not.toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(reads()).toHaveLength(1);
  });

  it("regression: server refusal leaves the fact unchanged and visible instead of silent refresh", async () => {
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : activityResponse(422));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Сервер отклонил запись активности");
    expect(screen.getByText("25")).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    expect(reads()).toHaveLength(1);
  });

  it("regression: serialize clicks across metrics while a non-idempotent write is pending", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : pending);
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    const buttons = screen.getAllByRole("button", { name: "+1" });
    fireEvent.click(buttons[0]);
    fireEvent.click(buttons[1]);
    expect(posts()).toHaveLength(1);
    expect(buttons.every((button) => button.hasAttribute("disabled"))).toBe(true);
    await act(async () => { finish(await activityResponse(200)); });
    await waitFor(() => expect(reads()).toHaveLength(2));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
  });

  it("network loss blocks resending until an explicit successful read and fact review", async () => {
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : Promise.reject(new TypeError("connection lost")));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Она могла сохраниться");
    expect(screen.queryByRole("button", { name: "Факт проверен" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[1]);
    expect(posts()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Обновить показатели" }));
    await screen.findByRole("button", { name: "Факт проверен" });
    expect(screen.getAllByRole("button", { name: "+1" }).every((button) => button.hasAttribute("disabled"))).toBe(true);
    expect(posts()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Факт проверен" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "+1" }).every((button) => !button.hasAttribute("disabled"))).toBe(true);
  });

  it.each([408, 500, 502])("does not auto-repeat an activity with uncertain HTTP outcome %i", async (code) => {
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : activityResponse(code));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось подтвердить запись");
    expect(posts()).toHaveLength(1);
    expect(reads()).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "+1" })[1]).toBeDisabled();
  });

  it("does not accept malformed successful response as a confirmed activity", async () => {
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? okJson(ROWS) : activityResponse(200, {}));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось подтвердить запись");
    expect(reads()).toHaveLength(1);
  });

  it("a failed verification read cannot enable acknowledgement or another activity", async () => {
    let rejectRead = false;
    fetchMock.mockImplementation((url: string) => url.includes("/kpis") ? (rejectRead ? failStatus(503) : okJson(ROWS)) : activityResponse(502));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    await screen.findByRole("alert");
    rejectRead = true;
    fireEvent.click(screen.getByRole("button", { name: "Обновить показатели" }));
    await screen.findByText("Не удалось загрузить показатели.");
    expect(screen.queryByText("Звонки")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Факт проверен" })).not.toBeInTheDocument();
    expect(posts()).toHaveLength(1);
    rejectRead = false;
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("button", { name: "Факт проверен" })).toBeInTheDocument();
    expect(posts()).toHaveLength(1);
  });

  it("successful POST plus failed GET reports recorded activity and retries reads only", async () => {
    let readCount = 0;
    fetchMock.mockImplementation((url: string) => url.includes("/kpis")
      ? (++readCount === 2 ? failStatus(503) : okJson(ROWS)) : activityResponse(200));
    render(<DayScoreboard />);
    await screen.findByText("Звонки");
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Активность записана");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await screen.findByText("Звонки");
    expect(posts()).toHaveLength(1);
    expect(reads()).toHaveLength(3);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("late old-period data cannot replace a newer selected period", async () => {
    let finishDay!: (value: Response) => void;
    const pendingDay = new Promise<Response>((resolve) => { finishDay = resolve; });
    fetchMock.mockImplementation((url: string) => url.includes("period=day") ? pendingDay
      : okJson(ROWS.map((row) => ({ ...row, actual: 700 }))));
    render(<DayScoreboard />);
    await waitFor(() => expect(reads()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    await screen.findByText("Звонки");
    expect(screen.getAllByText("700")).toHaveLength(2);
    await act(async () => { finishDay(await okJson(ROWS)); });
    await waitFor(() => expect(screen.queryByText("25")).not.toBeInTheDocument());
    expect(screen.getAllByText("700")).toHaveLength(2);
  });
});


describe("DayScoreboard unchanged period selection", () => {
  it("clicking the active period keeps its pending read valid", async () => {
    let finish!: (value: Response) => void;
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(<DayScoreboard />);
    await waitFor(() => expect(reads()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "День" }));
    await act(async () => { finish(await okJson(ROWS)); });
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    expect(reads()).toHaveLength(1);
  });
});
