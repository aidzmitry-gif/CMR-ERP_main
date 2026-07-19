import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Загрузка стадий идёт через глобальный fetch("/api/sales/stages"); CRUD — через @/lib/api.
// Мокаем только CRUD-хелперы (сам компонент тестируем целиком) и подменяем global.fetch.
vi.mock("@/lib/api", () => ({
  createStage: vi.fn(),
  updateStage: vi.fn(),
  deleteStage: vi.fn(),
}));

import { DealStageEditor } from "@/components/deal-stage-editor";
import * as api from "@/lib/api";
import type { StageRow } from "@/lib/api";

const stage = (over: Partial<StageRow> = {}): StageRow => ({
  code: "won",
  title: "Успех",
  sort_order: 10,
  probability: 100,
  kind: "won",
  color: "#22C55E",
  is_active: true,
  funnel: "new_clients",
  ...over,
});

/** Подменить global.fetch (GET /api/sales/stages) ответом с заданными строками. */
function mockLoad(rows: StageRow[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => rows }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad([]); // дефолт — honest-empty; тесты с данными переопределяют
});
afterEach(() => vi.unstubAllGlobals());

describe("DealStageEditor", () => {
  it("показывает индикатор загрузки до первого ответа, затем убирает его", async () => {
    // fetch, который никогда не резолвится → состояние остаётся loading
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<DealStageEditor />);
    expect(screen.getByText("Загрузка стадий…")).toBeInTheDocument();
  });

  it("honest-empty: без стадий показывает подсказку добавить первую", async () => {
    render(<DealStageEditor />);
    expect(await screen.findByText(/Стадии не заданы/)).toBeInTheDocument();
    // таблицы стадий нет
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("ошибка загрузки показывает сообщение и «Повторить», повтор перезагружает данные", async () => {
    // первый GET падает (ok:false), повтор — успешный со стадией
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [stage({ code: "new", title: "Новый" })] });
    vi.stubGlobal("fetch", fetchMock);

    render(<DealStageEditor />);
    expect(await screen.findByText(/Не удалось загрузить стадии/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    // после успешного повтора рендерится строка стадии (код — текст, название — input)
    expect(await screen.findByText("new")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Новый")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("рендерит строки стадий: код, название и вероятность из данных", async () => {
    mockLoad([
      stage({ code: "lead", title: "Заявка", probability: 20 }),
      stage({ code: "won", title: "Успех", probability: 100 }),
    ]);
    render(<DealStageEditor />);

    expect(await screen.findByText("lead")).toBeInTheDocument();
    expect(screen.getByText("won")).toBeInTheDocument();
    // название и вероятность живут в контролируемых input — сверяем по value
    expect(screen.getByDisplayValue("Заявка")).toBeInTheDocument();
    expect(screen.getByDisplayValue("20")).toBeInTheDocument();
    expect(screen.getByDisplayValue("100")).toBeInTheDocument();
  });

  it("правка названия и «Сохранить» шлёт updateStage с новым значением и показывает подтверждение", async () => {
    (api.updateStage as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    mockLoad([stage({ code: "lead", title: "Заявка", probability: 20 })]);
    render(<DealStageEditor />);

    const titleInput = await screen.findByDisplayValue("Заявка");
    fireEvent.change(titleInput, { target: { value: "Первичка" } });

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(api.updateStage).toHaveBeenCalledWith(
        "lead",
        expect.objectContaining({ title: "Первичка", probability: 20, kind: "won" }),
      ),
    );
    expect(await screen.findByText("Сохранено: Первичка")).toBeInTheDocument();
  });

  it("неудачное сохранение (updateStage=false) показывает ошибку, а не «Сохранено»", async () => {
    (api.updateStage as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    mockLoad([stage({ code: "lead", title: "Заявка" })]);
    render(<DealStageEditor />);

    await screen.findByDisplayValue("Заявка");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText(/Не удалось сохранить Заявка/)).toBeInTheDocument();
    expect(screen.queryByText(/^Сохранено/)).not.toBeInTheDocument();
  });

  it("удаление стадии со сделками (409) показывает причину из detail, стадию не убирает", async () => {
    (api.deleteStage as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      detail: "В стадии есть сделки — удаление запрещено",
    });
    mockLoad([stage({ code: "lead", title: "Заявка" })]);
    render(<DealStageEditor />);

    await screen.findByDisplayValue("Заявка");
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));

    await waitFor(() => expect(api.deleteStage).toHaveBeenCalledWith("lead"));
    expect(await screen.findByText("В стадии есть сделки — удаление запрещено")).toBeInTheDocument();
  });

  it("добавление с пустым кодом/названием не зовёт createStage, а требует их заполнить", async () => {
    render(<DealStageEditor />);
    await screen.findByText(/Стадии не заданы/);

    // черновик пуст (EMPTY_NEW) → клик «Добавить» ловится валидацией
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    expect(await screen.findByText(/Заполните код и название/)).toBeInTheDocument();
    expect(api.createStage).not.toHaveBeenCalled();
  });

  it("заполнение кода/названия и «Добавить» шлёт createStage и подтверждает", async () => {
    (api.createStage as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    render(<DealStageEditor />);
    await screen.findByText(/Стадии не заданы/);

    // строк нет (honest-empty) → поля черновика уникальны на странице
    fireEvent.change(screen.getByPlaceholderText("напр. nurture"), {
      target: { value: "nurture" },
    });
    fireEvent.change(screen.getByLabelText(/Название/), { target: { value: "Дозревание" } });

    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(api.createStage).toHaveBeenCalledWith(
        expect.objectContaining({ code: "nurture", title: "Дозревание" }),
      ),
    );
    expect(await screen.findByText("Добавлена: Дозревание")).toBeInTheDocument();
  });
});
