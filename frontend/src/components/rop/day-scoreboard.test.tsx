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

function okJson(data: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => data } as Response);
}
function failStatus(status: number) {
  return Promise.resolve({ ok: false, status, json: async () => ({ detail: "failed" }) } as unknown as Response);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  // По умолчанию KPI отдаёт ROWS, а POST — фактическую форму подтверждённого backend receipt.
  fetchMock.mockImplementation((url: string) => {
    if (typeof url === "string" && url.includes("/api/sales/kpis")) return okJson(ROWS);
    if (typeof url === "string" && url.includes("/api/sales/activities")) {
      return okJson({ ok: true, date: "2026-10-17" }, 201);
    }
    return okJson({});
  });
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

  it("DS-GET-MALFORMED: некорректные строки не превращаются в пустой успешный список", async () => {
    const malformed: unknown[] = [
      {},
      [{ key: "calls", title: "Звонки", target: 20, actual: 4, percent: 20 }],
      [{ key: "calls", title: "Звонки", target: Number.NaN, actual: 4, percent: 20, unit: "count" }],
      [ROWS[0], { ...ROWS[1], key: ROWS[0].key }],
      [{ ...ROWS[0], unit: "hours" }],
    ];
    fetchMock.mockImplementationOnce(() => okJson(malformed[0]));
    const view = render(<DayScoreboard />);

    for (const payload of malformed) {
      if (payload !== malformed[0]) {
        fetchMock.mockImplementationOnce(() => okJson(payload));
        fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
      }
      expect(await screen.findByText(/Сервер вернул некорректный список показателей/)).toBeInTheDocument();
      expect(screen.queryByText(/Плановые показатели не заданы/)).not.toBeInTheDocument();
      expect(screen.queryByText("Звонки")).not.toBeInTheDocument();
    }

    fetchMock.mockImplementationOnce(() => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => { throw new SyntaxError("invalid JSON"); },
    } as Response));
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText(/Сервер вернул некорректный список показателей/)).toBeInTheDocument();
    expect(screen.queryByText(/Проверьте соединение/)).not.toBeInTheDocument();
    view.unmount();
  });

  it("DS-GET-NETWORK-RETRY: сетевая ошибка видна и явный повтор загружает строки", async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new Error("network down")));
    render(<DayScoreboard />);

    expect(await screen.findByText(/Не удалось загрузить показатели/)).toBeInTheDocument();
    expect(screen.queryByText(/Плановые показатели не заданы/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("DS-GET-REFRESH-STALE: сбой обновления сохраняет явный stale-срез и блокирует запись", async () => {
    let getCount = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/sales/kpis")) {
        getCount += 1;
        return getCount === 2 ? failStatus(503) : okJson(ROWS);
      }
      return okJson({ ok: true, date: "2026-10-17" }, 201);
    });
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);

    expect(await screen.findByText("Отметка подтверждена за 2026-10-17.")).toBeInTheDocument();
    expect(screen.getByText("Звонки")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/HTTP 503.*предыдущий срез; запись заблокирована/);
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(getCount).toBe(3));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText("Отметка подтверждена за 2026-10-17.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeEnabled();
  });

  it("DS-GET-CONTEXT-SWITCH: при смене периода старые строки скрываются до нового ответа", async () => {
    const week = deferred<Response>();
    fetchMock.mockImplementation((url: string) => url.includes("period=week")
      ? week.promise
      : okJson(ROWS));
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("period=week"))).toBe(true));
    expect(screen.queryByText("Звонки")).not.toBeInTheDocument();
    expect(screen.getAllByText("загрузка")).toHaveLength(6);
    await act(async () => week.resolve(await okJson([{ ...ROWS[0], key: "week-calls", title: "Звонки за неделю" }])));
    expect(await screen.findByText("Звонки за неделю")).toBeInTheDocument();
  });

  it("DS-GET-ABA: запоздавший ответ первого A не перезаписывает новый A после A→B→A", async () => {
    const firstDay = deferred<Response>();
    const week = deferred<Response>();
    const secondDay = deferred<Response>();
    let dayCount = 0;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("period=week")) return week.promise;
      dayCount += 1;
      return dayCount === 1 ? firstDay.promise : secondDay.promise;
    });
    render(<DayScoreboard />);
    await waitFor(() => expect(dayCount).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("period=week"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "День" }));
    await waitFor(() => expect(dayCount).toBe(2));

    await act(async () => secondDay.resolve(await okJson([{ ...ROWS[0], title: "Новый день" }])));
    expect(await screen.findByText("Новый день")).toBeInTheDocument();
    await act(async () => firstDay.resolve(await okJson([{ ...ROWS[0], title: "Старый день" }])));
    expect(screen.getByText("Новый день")).toBeInTheDocument();
    expect(screen.queryByText("Старый день")).not.toBeInTheDocument();
    await act(async () => week.resolve(await okJson(ROWS)));
  });

  it("DS-GET-UNMOUNT: GET отменяется при unmount, а поздний ответ не запускает побочные вызовы", async () => {
    const pending = deferred<Response>();
    fetchMock.mockImplementationOnce(() => pending.promise);
    const view = render(<DayScoreboard />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    const signal = requestInit.signal as AbortSignal;

    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(await okJson(ROWS)));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("DS-WRITE-REJECT: только HTTP 401/403/422 освобождают lock для явного повтора", async () => {
    for (const status of [401, 403, 422]) {
      fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
        ? okJson(ROWS)
        : failStatus(status));
      const view = render(<DayScoreboard />);
      expect(await screen.findByText("Звонки")).toBeInTheDocument();
      const postCountBefore = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities")).length;
      fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
      expect(await screen.findByRole("alert")).toHaveTextContent(`HTTP ${status}`);

      fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
        ? okJson(ROWS)
        : okJson({ ok: true, date: "2026-10-17" }, 201));
      await waitFor(() => expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeEnabled());
      fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
      expect(await screen.findByText(/Отметка подтверждена за 2026-10-17/)).toBeInTheDocument();
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities")).length - postCountBefore).toBe(2);
      view.unmount();
    }
  });

  it("DS-WRITE-SINGLEFLIGHT: быстрые клики по нескольким строкам дают один POST с прежним телом", async () => {
    const post = deferred<Response>();
    fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
      ? okJson(ROWS)
      : post.promise);
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "+1" });

    act(() => {
      fireEvent.click(buttons[0]);
      fireEvent.click(buttons[1]);
    });

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"))).toHaveLength(1));
    const [url, init] = fetchMock.mock.calls.find(([candidate]) => String(candidate).includes("/api/sales/activities"))!;
    expect(url).toBe("/api/sales/activities");
    expect(init).toMatchObject({ method: "POST", headers: { "Content-Type": "application/json" } });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ kpi_key: "calls", value: 1 });
    await act(async () => post.resolve(await okJson({ ok: true, date: "2026-10-17" }, 201)));
    expect(await screen.findByText("Отметка подтверждена за 2026-10-17.")).toBeInTheDocument();
  });

  it("DS-WRITE-NETWORK-HOLD: сетевая неопределённость переживает успешные GET и смену периода", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/sales/kpis")) {
        return okJson(url.includes("period=week") ? [{ ...ROWS[0], title: "Звонки недели" }] : ROWS);
      }
      return Promise.reject(new Error("network down"));
    });
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Результат отметки не подтверждён/);

    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    expect(await screen.findByText("Звонки недели")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Результат отметки не подтверждён/);
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"))).toHaveLength(1);
  });

  it("DS-WRITE-5XX-HOLD: HTTP 5xx не подтверждает POST и GET не снимает блокировку", async () => {
    fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
      ? okJson(ROWS)
      : failStatus(503));
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"))).toHaveLength(1);
  });

  it("DS-WRITE-MALFORMED-2XX: неподтверждённые 2xx-ответы удерживают глобальный lock", async () => {
    const cases: Array<{ status: number; body: unknown }> = [
      { status: 200, body: { ok: true, date: "2026-10-17" } },
      { status: 201, body: { ok: true } },
      { status: 201, body: { ok: true, date: "2026-02-30" } },
    ];
    for (const item of cases) {
      fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
        ? okJson(ROWS)
        : okJson(item.body, item.status));
      const view = render(<DayScoreboard />);
      expect(await screen.findByText("Звонки")).toBeInTheDocument();
      const postCountBefore = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities")).length;
      fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
      expect(await screen.findByRole("alert")).toHaveTextContent(/Результат отметки не подтверждён/);
      expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities")).length - postCountBefore).toBe(1);
      view.unmount();
    }
  });

  it("DS-WRITE-CONTEXT-CURRENT: POST под днём после завершения перечитывает выбранную неделю", async () => {
    const post = deferred<Response>();
    const weekRows = [{ ...ROWS[0], key: "week-calls", title: "Звонки недели" }];
    const getPeriods: string[] = [];
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/sales/kpis")) {
        getPeriods.push(url.includes("period=week") ? "week" : "day");
        return okJson(url.includes("period=week") ? weekRows : ROWS);
      }
      return post.promise;
    });
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/sales/activities"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    expect(await screen.findByText("Звонки недели")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"))).toHaveLength(1);

    await act(async () => post.resolve(await okJson({ ok: true, date: "2026-10-17" }, 201)));
    expect(await screen.findByText("Отметка подтверждена за 2026-10-17.")).toBeInTheDocument();
    expect(getPeriods.filter((value) => value === "day")).toHaveLength(1);
    expect(getPeriods.filter((value) => value === "week")).toHaveLength(2);
  });

  it("DS-WRITE-ABA-HOLD: неизвестный POST сохраняет lock после A→B→A и успешного GET", async () => {
    const post = deferred<Response>();
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/sales/kpis")) return okJson(ROWS);
      return post.promise;
    });
    render(<DayScoreboard />);
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/sales/activities"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Неделя" }));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "День" }));
    expect(await screen.findByText("Звонки")).toBeInTheDocument();

    await act(async () => post.resolve(await failStatus(503)));
    expect(await screen.findByRole("alert")).toHaveTextContent(/HTTP 503/);
    expect(screen.getAllByRole("button", { name: "+1" })[0]).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/activities"))).toHaveLength(1);
  });

  it("DS-WRITE-UNMOUNT: поздний подтверждённый POST после unmount не запускает GET или UI", async () => {
    for (const outcome of ["resolve", "reject"] as const) {
      const body = deferred<unknown>();
      const readBody = vi.fn(() => body.promise);
      fetchMock.mockImplementation((url: string) => url.includes("/api/sales/kpis")
        ? okJson(ROWS)
        : Promise.resolve({ ok: true, status: 201, json: readBody } as unknown as Response));
      const view = render(<DayScoreboard />);
      expect(await screen.findByText("Звонки")).toBeInTheDocument();
      fireEvent.click(screen.getAllByRole("button", { name: "+1" })[0]);
      await waitFor(() => expect(readBody).toHaveBeenCalledTimes(1));
      const getCount = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/kpis")).length;
      view.unmount();

      await act(async () => {
        if (outcome === "resolve") body.resolve({ ok: true, date: "2026-10-17" });
        else body.reject(new SyntaxError("invalid JSON"));
        await body.promise.catch(() => undefined);
      });
      expect(view.container).toBeEmptyDOMElement();
      expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sales/kpis"))).toHaveLength(getCount);
    }
  });
});
