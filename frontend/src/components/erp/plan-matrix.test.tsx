import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем только сетевые мутации/загрузки модуля production-plan; чистые функции
// (fmtNh, loadTone) оставляем настоящими — компонент проверяем на реальном форматировании.
vi.mock("@/lib/production-plan", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/production-plan")>();
  return {
    ...actual,
    fetchPlan: vi.fn(),
    putPlanCell: vi.fn(),
    upsertPosition: vi.fn(),
    deletePosition: vi.fn(),
  };
});

import { PlanMatrix } from "@/components/erp/plan-matrix";
import * as plan from "@/lib/production-plan";
import type { PlanBoard } from "@/lib/production-plan";

// Фикстура доски: одно изделие с планом/фактом в январе, мощность 176 н.ч/мес.
function makeBoard(overrides: Partial<PlanBoard> = {}): PlanBoard {
  const months = Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    plan_qty: i === 0 ? 10 : 0,
    plan_nh: i === 0 ? 20 : 0,
    fact_qty: i === 0 ? 5 : 0,
    fact_nh: i === 0 ? 10 : 0,
  }));
  const month_nh = Array.from({ length: 12 }, (_, i) => (i === 0 ? 20 : 0));
  const fact_nh = Array.from({ length: 12 }, (_, i) => (i === 0 ? 10 : 0));
  const load_pct = month_nh.map((nh) => (nh / 176) * 100);
  return {
    year: 2026,
    capacity_nh: 176,
    rows: [{ product: "Корпус", norm_nh: 2, months, year_qty: 10, year_nh: 20 }],
    totals: {
      month_nh,
      fact_nh,
      load_pct,
      year_nh: 20,
      plan_ytd: 20,
      fact_ytd: 10,
      peak_month: 0,
      low_month: 1,
    },
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("PlanMatrix", () => {
  it("без данных показывает подсказку о недоступности сервера", () => {
    render(<PlanMatrix initial={null} />);
    expect(screen.getByText(/Данные планирования недоступны/)).toBeInTheDocument();
    expect(screen.queryByText("Изделие")).not.toBeInTheDocument();
  });

  it("рендерит KPI-шапку с мощностью, План/Факт YTD и пиковым месяцем", () => {
    render(<PlanMatrix initial={makeBoard()} />);
    // fmtNh форматирует с запятой и одним знаком
    expect(screen.getByText("176,0 н.ч/мес")).toBeInTheDocument();
    expect(screen.getByText("20,0 н.ч")).toBeInTheDocument(); // План YTD
    expect(screen.getByText("10,0 н.ч")).toBeInTheDocument(); // Факт YTD
    expect(screen.getByText("Пик: Янв")).toBeInTheDocument(); // peak_month=0
    expect(screen.getByText("2026")).toBeInTheDocument();
  });

  it("рендерит строку изделия с нормой и годовым итогом", () => {
    render(<PlanMatrix initial={makeBoard()} />);
    expect(screen.getByText("Корпус")).toBeInTheDocument();
    expect(screen.getByText(/2,0 н\.ч/)).toBeInTheDocument(); // norm_nh=2 в скобках
    // строка «Загрузка %» показывает 11% (20/176*100, округл.)
    expect(screen.getByText("11%")).toBeInTheDocument();
  });

  it("клик по ячейке открывает инпут, изменение+blur зовёт putPlanCell с новым кол-вом", async () => {
    const updated = makeBoard();
    updated.rows[0].months[0].plan_qty = 25;
    updated.rows[0].year_qty = 25;
    (plan.putPlanCell as ReturnType<typeof vi.fn>).mockResolvedValue(updated);

    render(<PlanMatrix initial={makeBoard()} />);
    // кнопка ячейки января с планом 10
    fireEvent.click(screen.getByRole("button", { name: "10" }));
    const input = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(input.value).toBe("10");

    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(plan.putPlanCell).toHaveBeenCalledWith(
        expect.objectContaining({ year: 2026, product: "Корпус", month: 1, plan_qty: 25 }),
      ),
    );
    // доска обновилась — годовой итог стал 25 (появляется и в ячейке, и в «Итого»)
    expect((await screen.findAllByText("25")).length).toBeGreaterThan(0);
  });

  it("blur без изменения кол-ва не дёргает putPlanCell (ранний return)", async () => {
    render(<PlanMatrix initial={makeBoard()} />);
    fireEvent.click(screen.getByRole("button", { name: "10" }));
    const input = screen.getByRole("spinbutton");
    fireEvent.blur(input); // значение не менялось: 10 === plan_qty
    await waitFor(() => expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument());
    expect(plan.putPlanCell).not.toHaveBeenCalled();
  });

  it("удаление позиции зовёт deletePosition и перезагружает доску", async () => {
    (plan.deletePosition as ReturnType<typeof vi.fn>).mockResolvedValue(true);
    const reloaded = makeBoard({ rows: [] });
    (plan.fetchPlan as ReturnType<typeof vi.fn>).mockResolvedValue(reloaded);

    render(<PlanMatrix initial={makeBoard()} />);
    fireEvent.click(screen.getByTitle("Удалить позицию"));

    await waitFor(() => expect(plan.deletePosition).toHaveBeenCalledWith(2026, "Корпус"));
    // после удаления строка изделия ушла
    await waitFor(() => expect(screen.queryByText("Корпус")).not.toBeInTheDocument());
  });

  it("форма добавления позиции: раскрытие, ввод и «Добавить» зовёт upsertPosition", async () => {
    const withNew = makeBoard();
    withNew.rows.push({
      product: "Крышка",
      norm_nh: 0,
      months: Array.from({ length: 12 }, (_, i) => ({
        month: i + 1,
        plan_qty: 0,
        plan_nh: 0,
        fact_qty: 0,
        fact_nh: 0,
      })),
      year_qty: 3,
      year_nh: 0,
    });
    (plan.upsertPosition as ReturnType<typeof vi.fn>).mockResolvedValue(withNew);

    render(<PlanMatrix initial={makeBoard()} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить позицию/ }));
    const form = screen.getByPlaceholderText("Название изделия") as HTMLInputElement;
    fireEvent.change(form, { target: { value: "Крышка" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(plan.upsertPosition).toHaveBeenCalledWith(
        expect.objectContaining({ year: 2026, product: "Крышка", monthly: expect.any(Array) }),
      ),
    );
    // форма закрылась, новое изделие в таблице
    expect(screen.queryByPlaceholderText("Название изделия")).not.toBeInTheDocument();
    expect(await screen.findByText("Крышка")).toBeInTheDocument();
  });

  it("кнопка «Добавить» заблокирована при пустом названии изделия", () => {
    render(<PlanMatrix initial={makeBoard()} />);
    fireEvent.click(screen.getByRole("button", { name: /Добавить позицию/ }));
    expect(screen.getByRole("button", { name: "Добавить" })).toBeDisabled();
  });

  it("навигация по годам зовёт fetchPlan и переключает подпись года", async () => {
    (plan.fetchPlan as ReturnType<typeof vi.fn>).mockResolvedValue(makeBoard({ year: 2027 }));
    render(<PlanMatrix initial={makeBoard()} />);

    fireEvent.click(screen.getByRole("button", { name: "›" }));
    await waitFor(() => expect(plan.fetchPlan).toHaveBeenCalledWith(2027));
    expect(await screen.findByText("2027")).toBeInTheDocument();
  });
});
