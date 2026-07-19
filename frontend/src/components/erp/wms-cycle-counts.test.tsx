import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// Мокаем ТОЛЬКО сетевые функции слоя WMS; dueState — настоящий чистый хелпер.
vi.mock("@/lib/wms-warehouse", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-warehouse")>();
  return {
    ...actual,
    createCyclePlan: vi.fn(),
    fetchCyclePlans: vi.fn().mockResolvedValue([]),
    runCyclePlan: vi.fn(),
  };
});

import { WmsCycleCounts } from "@/components/erp/wms-cycle-counts";
import * as wh from "@/lib/wms-warehouse";
import type { CyclePlan } from "@/lib/wms-warehouse";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const TODAY = "2026-07-19";

function plan(over: Partial<CyclePlan> = {}): CyclePlan {
  return {
    id: 1,
    warehouse: "Главный",
    zone: null,
    cadence_days: 30,
    next_due_date: null,
    last_run_at: null,
    active: true,
    abc_class: null,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wh.fetchCyclePlans).mockResolvedValue([]);
  asMock(wh.createCyclePlan).mockResolvedValue(undefined);
  asMock(wh.runCyclePlan).mockResolvedValue(null);
});

describe("WmsCycleCounts", () => {
  it("пустой список планов показывает заглушку «Планов пока нет»", () => {
    render(<WmsCycleCounts initial={[]} today={TODAY} />);
    expect(screen.getByText("Планов пока нет")).toBeInTheDocument();
  });

  it("рендерит строки с реальными due-состояниями (просрочено/сегодня/предстоит/—)", () => {
    const overdue = plan({ id: 1, warehouse: "Склад-1", next_due_date: "2026-07-01" });
    const today = plan({ id: 2, warehouse: "Склад-2", next_due_date: TODAY });
    const upcoming = plan({ id: 3, warehouse: "Склад-3", next_due_date: "2026-08-01" });
    const none = plan({ id: 4, warehouse: "Склад-4", next_due_date: null, zone: "Зона А" });

    render(<WmsCycleCounts initial={[overdue, today, upcoming, none]} today={TODAY} />);

    expect(screen.getByText("Просрочено")).toBeInTheDocument();
    expect(screen.getByText("Сегодня")).toBeInTheDocument();
    expect(screen.getByText("Предстоит")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);

    // зона: указанная выводится как есть, пустая — «весь склад»
    expect(screen.getByText("Зона А")).toBeInTheDocument();
    expect(screen.getAllByText("весь склад").length).toBe(3);
    // период выводится с суффиксом «дн»
    expect(screen.getAllByText("30 дн").length).toBe(4);
  });

  it("создание плана шлёт trimmed поля и число периода, затем обновляет список из бэкенда", async () => {
    asMock(wh.fetchCyclePlans).mockResolvedValue([
      plan({ id: 9, warehouse: "Новый склад", cadence_days: 14, next_due_date: TODAY }),
    ]);

    render(<WmsCycleCounts initial={[]} today={TODAY} />);

    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "  Новый склад  " } });
    fireEvent.change(screen.getByPlaceholderText("Зона (опц.)"), { target: { value: "  Б  " } });
    fireEvent.change(screen.getByPlaceholderText("Период, дн"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: /План/ }));

    await waitFor(() =>
      expect(wh.createCyclePlan).toHaveBeenCalledWith({
        warehouse: "Новый склад",
        zone: "Б",
        cadence_days: 14,
        next_due_date: TODAY,
      }),
    );
    expect(wh.fetchCyclePlans).toHaveBeenCalled();
    expect(await screen.findByText("Новый склад")).toBeInTheDocument();
  });

  it("пустая зона отправляется как null, а нечисловой период — как 30 по умолчанию", async () => {
    render(<WmsCycleCounts initial={[]} today={TODAY} />);

    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "Склад X" } });
    fireEvent.change(screen.getByPlaceholderText("Период, дн"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: /План/ }));

    await waitFor(() =>
      expect(wh.createCyclePlan).toHaveBeenCalledWith({
        warehouse: "Склад X",
        zone: null,
        cadence_days: 30,
        next_due_date: TODAY,
      }),
    );
  });

  it("пустой склад (после очистки поля по умолчанию) не отправляет запрос на создание плана", () => {
    render(<WmsCycleCounts initial={[]} today={TODAY} />);
    fireEvent.change(screen.getByPlaceholderText("Склад"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: /План/ }));
    expect(wh.createCyclePlan).not.toHaveBeenCalled();
  });

  it("запуск плана с возвращённым документом переходит на страницу инвентаризации", async () => {
    asMock(wh.runCyclePlan).mockResolvedValue({ id: 555 });
    render(<WmsCycleCounts initial={[plan({ id: 3 })]} today={TODAY} />);

    fireEvent.click(screen.getByRole("button", { name: /Запустить/ }));

    await waitFor(() => expect(wh.runCyclePlan).toHaveBeenCalledWith(3));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/erp/wms/inventory/555"));
    expect(wh.fetchCyclePlans).not.toHaveBeenCalled();
  });

  it("запуск плана без документа не переходит, а обновляет список планов", async () => {
    asMock(wh.runCyclePlan).mockResolvedValue(null);
    render(<WmsCycleCounts initial={[plan({ id: 7 })]} today={TODAY} />);

    fireEvent.click(screen.getByRole("button", { name: /Запустить/ }));

    await waitFor(() => expect(wh.runCyclePlan).toHaveBeenCalledWith(7));
    await waitFor(() => expect(wh.fetchCyclePlans).toHaveBeenCalled());
    expect(pushMock).not.toHaveBeenCalled();
  });
});
