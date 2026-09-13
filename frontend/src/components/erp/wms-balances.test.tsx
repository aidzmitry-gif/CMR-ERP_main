import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// next/link → простая <a> (в jsdom роутинга нет).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Мокаем ТОЛЬКО сетевую функцию слоя WMS.
vi.mock("@/lib/wms-ops", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-ops")>();
  return {
    ...actual,
    fetchBalances: vi.fn().mockResolvedValue({ rows: [], sku_count: 0 }),
  };
});

import { WmsBalances } from "@/components/erp/wms-balances";
import * as wms from "@/lib/wms-ops";
import type { BalanceRow, Balances } from "@/lib/wms-ops";

function row(over: Partial<BalanceRow> = {}): BalanceRow {
  return {
    sku_code: "6СТ-190",
    sku_title: "Аккумулятор 190Ah",
    warehouse: "Главный",
    location_id: 10,
    location_code: "A-01",
    batch_ref: "П-1",
    qty: 5,
    ...over,
  };
}

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  asMock(wms.fetchBalances).mockResolvedValue({ rows: [], sku_count: 0 });
});

describe("WmsBalances", () => {
  it("shows separate owners and preserves rows when reload fails", async () => {
    asMock(wms.fetchBalances).mockRejectedValueOnce(new Error("unavailable"));
    render(<WmsBalances initial={{ rows: [row({ organization_id: 7 }), row({ organization_id: 8, qty: 2 })], sku_count: 1 }} />);
    expect(screen.getByText("Юрлицо №7")).toBeInTheDocument();
    expect(screen.getByText("Юрлицо №8")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Показаны ранее загруженные данные");
    expect(screen.getByText("Юрлицо №7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Обновить/ })).toBeEnabled();
  });
  it("рендерит строки остатков: код, номенклатура, склад, ячейка, партия и число", () => {
    const initial: Balances = { rows: [row()], sku_count: 1 };
    render(<WmsBalances initial={initial} />);

    const table = within(screen.getByRole("table"));
    expect(table.getByText("6СТ-190")).toBeInTheDocument();
    expect(table.getByText("Аккумулятор 190Ah")).toBeInTheDocument();
    expect(table.getByText("Главный")).toBeInTheDocument();
    expect(table.getByText("A-01")).toBeInTheDocument();
    expect(table.getByText("П-1")).toBeInTheDocument();
    expect(table.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("SKU: 1")).toBeInTheDocument();
  });

  it("пустые название/ячейку/партию заменяет прочерком, положительный остаток окрашен как ink", () => {
    const initial: Balances = {
      rows: [row({ sku_title: "", location_code: "", batch_ref: "" })],
      sku_count: 1,
    };
    render(<WmsBalances initial={initial} />);

    const dashes = screen.getAllByText("—");
    expect(dashes).toHaveLength(3);
    const qtyCell = screen.getByText("5");
    expect(qtyCell.className).toMatch(/text-ink/);
    expect(qtyCell.className).not.toMatch(/text-red-600/);
  });

  it("отрицательный остаток окрашен красным и форматируется по-русски (разделитель тысяч)", () => {
    const initial: Balances = { rows: [row({ qty: -1234 })], sku_count: 1 };
    render(<WmsBalances initial={initial} />);

    const qtyCell = screen.getByText(
      (_content, el) => (el?.textContent ?? "").replace(/\s/g, " ") === "-1 234",
    );
    expect(qtyCell).toBeInTheDocument();
    expect(qtyCell.className).toMatch(/text-red-600/);
  });

  it("пустой список показывает заглушку «Нет строк по выбранным условиям»", () => {
    render(<WmsBalances initial={{ rows: [], sku_count: 0 }} />);
    expect(
      screen.getByText("Нет строк по выбранным условиям"),
    ).toBeInTheDocument();
  });

  it("поиск по коду SKU фильтрует строки без учёта регистра", () => {
    const initial: Balances = {
      rows: [row({ sku_code: "6СТ-190", sku_title: "Первый" }), row({ sku_code: "9СТ-77", sku_title: "Второй" })],
      sku_count: 2,
    };
    render(<WmsBalances initial={initial} />);

    fireEvent.change(screen.getByPlaceholderText("Поиск по коду или названию"), {
      target: { value: "6ст" },
    });

    expect(screen.getByText("Первый")).toBeInTheDocument();
    expect(screen.queryByText("Второй")).not.toBeInTheDocument();
  });

  it("поиск по названию SKU тоже фильтрует и при отсутствии совпадений показывает заглушку", () => {
    const initial: Balances = {
      rows: [row({ sku_code: "6СТ-190", sku_title: "Аккумулятор" })],
      sku_count: 1,
    };
    render(<WmsBalances initial={initial} />);

    fireEvent.change(screen.getByPlaceholderText("Поиск по коду или названию"), {
      target: { value: "аккум" },
    });
    expect(screen.getByText("Аккумулятор")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Поиск по коду или названию"), {
      target: { value: "нет такого" },
    });
    expect(
      screen.getByText("Нет строк по выбранным условиям"),
    ).toBeInTheDocument();
  });

  it("кнопка «Обновить» вызывает fetchBalances и подставляет новые данные", async () => {
    asMock(wms.fetchBalances).mockResolvedValue({
      rows: [row({ sku_code: "НОВЫЙ", sku_title: "Новая позиция" })],
      sku_count: 1,
    });
    render(<WmsBalances initial={{ rows: [], sku_count: 0 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    await waitFor(() => expect(wms.fetchBalances).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("НОВЫЙ")).toBeInTheDocument();
    expect(screen.getByText("SKU: 1")).toBeInTheDocument();
  });

  it("ссылка «Сверка с остатками 1С →» ведёт на /erp/wms/stock", () => {
    render(<WmsBalances initial={{ rows: [], sku_count: 0 }} />);
    const link = screen.getByRole("link", { name: "Сверка с остатками 1С →" });
    expect(link).toHaveAttribute("href", "/erp/wms/stock");
  });
});
