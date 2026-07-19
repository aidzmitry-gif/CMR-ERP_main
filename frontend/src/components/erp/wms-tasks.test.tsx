import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WmsTask } from "@/lib/wms-warehouse";

vi.mock("@/lib/wms-warehouse", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-warehouse")>();
  return {
    ...actual,
    fetchTasks: vi.fn().mockResolvedValue([]),
    patchTask: vi.fn().mockResolvedValue(true),
  };
});

import { WmsTasks } from "@/components/erp/wms-tasks";
import * as wms from "@/lib/wms-warehouse";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const tasks: WmsTask[] = [
  {
    id: 1,
    kind: "putaway",
    status: "open",
    sku_code: "SKU-001",
    qty: 12345,
    warehouse: "Минск",
    from_location_id: null,
    to_location_id: null,
    doc_ref: "PRC-100",
    assignee: "",
    priority: "normal",
    note: "",
    created_at: null,
    done_at: null,
  },
  {
    id: 2,
    kind: "pick",
    status: "in_progress",
    sku_code: "SKU-002",
    qty: 5,
    warehouse: "Минск",
    from_location_id: null,
    to_location_id: null,
    doc_ref: "",
    assignee: "",
    priority: "normal",
    note: "",
    created_at: null,
    done_at: null,
  },
  {
    id: 3,
    kind: "pick",
    status: "done",
    sku_code: "SKU-003",
    qty: 1,
    warehouse: "Минск",
    from_location_id: null,
    to_location_id: null,
    doc_ref: "",
    assignee: "",
    priority: "normal",
    note: "",
    created_at: null,
    done_at: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wms.fetchTasks).mockResolvedValue(tasks);
  asMock(wms.patchTask).mockResolvedValue(true);
});

describe("WmsTasks", () => {
  it("рендерит строки задач с типом, кодом, кол-вом (форматированным) и документом", () => {
    render(<WmsTasks initial={tasks} />);
    // "Размещение" встречается и в табе-кнопке, и в ячейке типа строки
    expect(screen.getAllByText("Размещение").length).toBe(2);
    expect(screen.getAllByText("Подбор").length).toBe(3); // таб + 2 строки
    expect(screen.getByText("SKU-001")).toBeInTheDocument();
    // formatNumber → разделитель разрядов ru-RU (неразрывный пробел)
    expect(screen.getByText("12 345")).toBeInTheDocument();
    expect(screen.getByText("PRC-100")).toBeInTheDocument();
    // пустой doc_ref рендерится как тире
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("статусы рендерятся русскими лейблами", () => {
    render(<WmsTasks initial={tasks} />);
    expect(screen.getByText("Открыта")).toBeInTheDocument();
    expect(screen.getByText("В работе")).toBeInTheDocument();
    expect(screen.getByText("Выполнена")).toBeInTheDocument();
  });

  it("пустой список показывает «Задач нет»", () => {
    render(<WmsTasks initial={[]} />);
    expect(screen.getByText("Задач нет")).toBeInTheDocument();
  });

  it("вкладки фильтруют по типу задачи: «Подбор» скрывает putaway-строки", () => {
    render(<WmsTasks initial={tasks} />);
    fireEvent.click(screen.getByRole("button", { name: "Подбор" }));
    expect(screen.queryByText("SKU-001")).not.toBeInTheDocument();
    expect(screen.getByText("SKU-002")).toBeInTheDocument();
    expect(screen.getByText("SKU-003")).toBeInTheDocument();
  });

  it("вкладка «Размещение» показывает только putaway-строку", () => {
    render(<WmsTasks initial={tasks} />);
    fireEvent.click(screen.getByRole("button", { name: "Размещение" }));
    expect(screen.getByText("SKU-001")).toBeInTheDocument();
    expect(screen.queryByText("SKU-002")).not.toBeInTheDocument();
  });

  it("для открытой putaway-задачи есть кнопка «В работу», поле ячейки и «Завершить»", () => {
    render(<WmsTasks initial={tasks} />);
    expect(screen.getByRole("button", { name: "В работу" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("ячейка id")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Завершить" }).length).toBe(2); // putaway open + pick in_progress
  });

  it("для задачи в статусе done действия отсутствуют (нет кнопок в её строке)", () => {
    render(<WmsTasks initial={tasks} />);
    const doneRow = screen.getByText("SKU-003").closest("tr") as HTMLElement;
    expect(doneRow.querySelector("button")).toBeNull();
  });

  it("клик «В работу» зовёт patchTask(id, {status: 'in_progress'}) и перечитывает список", async () => {
    render(<WmsTasks initial={tasks} />);
    fireEvent.click(screen.getByRole("button", { name: "В работу" }));

    await waitFor(() =>
      expect(wms.patchTask).toHaveBeenCalledWith(1, { status: "in_progress" }),
    );
    await waitFor(() => expect(wms.fetchTasks).toHaveBeenCalledTimes(1));
  });

  it("ввод ячейки для putaway-задачи и «Завершить» передаёт to_location_id числом", async () => {
    render(<WmsTasks initial={tasks} />);
    fireEvent.change(screen.getByPlaceholderText("ячейка id"), { target: { value: "42" } });

    const putawayRow = screen.getByText("SKU-001").closest("tr") as HTMLElement;
    fireEvent.click(
      Array.from(putawayRow.querySelectorAll("button")).find((b) => b.textContent === "Завершить") as HTMLElement,
    );

    await waitFor(() =>
      expect(wms.patchTask).toHaveBeenCalledWith(1, { status: "done", to_location_id: 42 }),
    );
  });

  it("«Завершить» для putaway без введённой ячейки передаёт to_location_id: null", async () => {
    render(<WmsTasks initial={tasks} />);
    const putawayRow = screen.getByText("SKU-001").closest("tr") as HTMLElement;
    fireEvent.click(
      Array.from(putawayRow.querySelectorAll("button")).find((b) => b.textContent === "Завершить") as HTMLElement,
    );

    await waitFor(() =>
      expect(wms.patchTask).toHaveBeenCalledWith(1, { status: "done", to_location_id: null }),
    );
  });

  it("«Завершить» для pick-задачи (in_progress) зовёт patchTask без to_location_id", async () => {
    render(<WmsTasks initial={tasks} />);
    const pickRow = screen.getByText("SKU-002").closest("tr") as HTMLElement;
    fireEvent.click(
      Array.from(pickRow.querySelectorAll("button")).find((b) => b.textContent === "Завершить") as HTMLElement,
    );

    await waitFor(() => expect(wms.patchTask).toHaveBeenCalledWith(2, { status: "done" }));
  });

  it("во время выполнения действия кнопки блокируются (disabled)", async () => {
    let resolveFn: (v: boolean) => void = () => {};
    asMock(wms.patchTask).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFn = resolve;
        }),
    );

    render(<WmsTasks initial={tasks} />);
    const btn = screen.getByRole("button", { name: "В работу" });
    fireEvent.click(btn);

    await waitFor(() => expect(btn).toBeDisabled());
    resolveFn(true);
    await waitFor(() => expect(wms.fetchTasks).toHaveBeenCalled());
  });
});
