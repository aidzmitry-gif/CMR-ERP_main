import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> (в jsdom роутинга нет; ссылка «Остаток из движений» — просто href).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевые функции слоя WMS; чистые хелперы (reasonLabel/locationLabel/
// REASON_LABELS) оставляем настоящими — они считают подписи по-настоящему.
vi.mock("@/lib/wms-ops", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-ops")>();
  return {
    ...actual,
    fetchMovements: vi.fn().mockResolvedValue([]),
    receipt: vi.fn().mockResolvedValue(true),
    shipment: vi.fn().mockResolvedValue(true),
    adjustment: vi.fn().mockResolvedValue(true),
    transfer: vi.fn().mockResolvedValue(true),
  };
});

import { WmsMovements } from "@/components/erp/wms-movements";
import * as wms from "@/lib/wms-ops";
import type { StockMovement, WmsLocation } from "@/lib/wms-ops";

function mv(over: Partial<StockMovement> = {}): StockMovement {
  return {
    id: 1,
    sku_code: "6СТ-190",
    warehouse: "Главный",
    kind: "in",
    qty: 5,
    reason: "receipt",
    location_id: null,
    batch_ref: "",
    doc_ref: "ПР-1",
    note: "",
    created_at: "2026-07-15T10:00:00",
    ...over,
  };
}

const inRow = mv({ id: 1, sku_code: "6СТ-190", kind: "in", qty: 5, reason: "receipt" });
const outRow = mv({ id: 2, sku_code: "6СТ-100", kind: "out", qty: 12, reason: "shipment", doc_ref: "" });

const locations: WmsLocation[] = [
  { id: 10, warehouse: "Главный", zone: "A", code: "01", title: "", is_active: true },
  { id: 11, warehouse: "Главный", zone: "B", code: "99", title: "", is_active: false },
  { id: 12, warehouse: "Второй", zone: "C", code: "07", title: "", is_active: true },
];

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wms.fetchMovements).mockResolvedValue([]);
  asMock(wms.receipt).mockResolvedValue(true);
  asMock(wms.shipment).mockResolvedValue(true);
  asMock(wms.adjustment).mockResolvedValue(true);
  asMock(wms.transfer).mockResolvedValue(true);
});

describe("WmsMovements", () => {
  it("рендерит журнал: русская подпись типа, знаковое кол-во и цвет прихода/расхода", () => {
    render(<WmsMovements initial={[inRow, outRow]} locations={[]} />);

    // подписи типов в журнале (внутри таблицы, вне панели операций) — из настоящего REASON_LABELS
    const journal = within(screen.getByRole("table"));
    expect(journal.getByText("Приёмка")).toBeInTheDocument();
    expect(journal.getByText("Отгрузка")).toBeInTheDocument();

    // приход: «+5» зелёный, расход: «−12» красный (минус — U+2212, как в компоненте)
    const inQty = screen.getByText("+5");
    const outQty = screen.getByText("−12");
    expect(inQty.className).toMatch(/text-green-600/);
    expect(outQty.className).toMatch(/text-red-600/);

    // SKU обеих строк на месте
    expect(screen.getByText("6СТ-190")).toBeInTheDocument();
    expect(screen.getByText("6СТ-100")).toBeInTheDocument();
  });

  it("пустой журнал показывает заглушку «Движений по фильтру нет»", () => {
    render(<WmsMovements initial={[]} locations={[]} />);
    expect(screen.getByText("Движений по фильтру нет")).toBeInTheDocument();
  });

  it("фильтр по типу движения прячет строки другого типа", () => {
    render(<WmsMovements initial={[inRow, outRow]} locations={[]} />);
    expect(screen.getByText("6СТ-190")).toBeInTheDocument();

    // выбор селекта журнала (тот, где есть опция «Все типы») → только «Отгрузка»
    const reasonSelect = screen
      .getAllByRole("combobox")
      .find((s) => s.textContent?.includes("Все типы")) as HTMLSelectElement;
    fireEvent.change(reasonSelect, { target: { value: "shipment" } });

    expect(screen.queryByText("6СТ-190")).not.toBeInTheDocument();
    expect(screen.getByText("6СТ-100")).toBeInTheDocument();
  });

  it("селект ячейки показывает только активные ячейки текущего склада", () => {
    render(<WmsMovements initial={[]} locations={locations} />);
    // склад по умолчанию «Главный»: активная A·01 есть, неактивная B·99 и чужой склад C·07 — нет
    expect(screen.getByRole("option", { name: "A · 01" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "B · 99" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "C · 07" })).not.toBeInTheDocument();
  });

  it("отправка без SKU/кол-ва показывает ошибку и не дёргает бэкенд", () => {
    render(<WmsMovements initial={[]} locations={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));

    expect(screen.getByText("Укажите SKU и количество")).toBeInTheDocument();
    expect(wms.receipt).not.toHaveBeenCalled();
  });

  it("успешная приёмка: qty с запятой парсится, зовётся receipt, показывается успех и журнал обновляется", async () => {
    asMock(wms.fetchMovements).mockResolvedValue([
      mv({ id: 9, sku_code: "НОВЫЙ-SKU", kind: "in", qty: 3, reason: "receipt" }),
    ]);
    render(<WmsMovements initial={[]} locations={[]} />);

    fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "6СТ-190" } });
    fireEvent.change(screen.getByPlaceholderText("Кол-во*"), { target: { value: "2,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));

    await waitFor(() =>
      expect(wms.receipt).toHaveBeenCalledWith(
        expect.objectContaining({ sku_code: "6СТ-190", qty: 2.5, warehouse: "Главный" }),
      ),
    );
    expect(await screen.findByText("Движение записано")).toBeInTheDocument();
    // refresh() подтянул новый журнал
    expect(wms.fetchMovements).toHaveBeenCalled();
    expect(await screen.findByText("НОВЫЙ-SKU")).toBeInTheDocument();
  });

  it("сбой записи показывает ошибку и НЕ обновляет журнал", async () => {
    asMock(wms.receipt).mockResolvedValue(false);
    render(<WmsMovements initial={[]} locations={[]} />);

    fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "6СТ-190" } });
    fireEvent.change(screen.getByPlaceholderText("Кол-во*"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));

    expect(await screen.findByText(/Не удалось записать/)).toBeInTheDocument();
    expect(wms.fetchMovements).not.toHaveBeenCalled();
  });

  it("переключение операции на «Отгрузка» шлёт shipment, а не receipt", async () => {
    render(<WmsMovements initial={[]} locations={[]} />);

    fireEvent.click(screen.getByRole("button", { name: /Отгрузка/ }));
    fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "6СТ-100" } });
    fireEvent.change(screen.getByPlaceholderText("Кол-во*"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Записать" }));

    await waitFor(() =>
      expect(wms.shipment).toHaveBeenCalledWith(
        expect.objectContaining({ sku_code: "6СТ-100", qty: 4 }),
      ),
    );
    expect(wms.receipt).not.toHaveBeenCalled();
  });

  it("кнопка «Обновить» перечитывает журнал из бэкенда", async () => {
    asMock(wms.fetchMovements).mockResolvedValue([
      mv({ id: 7, sku_code: "ОБНОВЛ-SKU", kind: "in", qty: 1, reason: "receipt" }),
    ]);
    render(<WmsMovements initial={[]} locations={[]} />);
    expect(screen.getByText("Движений по фильтру нет")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    await waitFor(() => expect(wms.fetchMovements).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("ОБНОВЛ-SKU")).toBeInTheDocument();
  });

  it("перемещение шлёт transfer с from/to ячейками", async () => {
    render(<WmsMovements initial={[]} locations={locations} />);

    fireEvent.click(screen.getByRole("button", { name: /Перемещение/ }));
    fireEvent.change(screen.getByPlaceholderText("Код SKU*"), { target: { value: "6СТ-190" } });
    fireEvent.change(screen.getByPlaceholderText("Кол-во*"), { target: { value: "2" } });

    // селекты «Из ячейки» / «В ячейку» — оба содержат активную A·01 (id 10)
    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    const fromSel = selects.find((s) => s.textContent?.includes("Из ячейки")) as HTMLSelectElement;
    const toSel = selects.find((s) => s.textContent?.includes("В ячейку")) as HTMLSelectElement;
    fireEvent.change(fromSel, { target: { value: "10" } });
    fireEvent.change(toSel, { target: { value: "10" } });

    fireEvent.click(screen.getByRole("button", { name: "Записать" }));

    await waitFor(() =>
      expect(wms.transfer).toHaveBeenCalledWith(
        expect.objectContaining({ sku_code: "6СТ-190", qty: 2, from_location_id: 10, to_location_id: 10 }),
      ),
    );
    expect(wms.receipt).not.toHaveBeenCalled();
  });
});
