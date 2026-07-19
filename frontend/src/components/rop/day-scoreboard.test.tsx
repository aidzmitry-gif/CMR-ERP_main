import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    typeof url === "string" && url.includes("/api/sales/kpis") ? okJson(ROWS) : okJson({}),
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
