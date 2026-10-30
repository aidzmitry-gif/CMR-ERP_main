import { configureCompany,render,resetCompany,waitForCompany } from "@/test/installation-company";
import { fireEvent,screen,waitFor,within } from "@testing-library/react";
import { beforeEach,beforeEach as configureBeforeEach,describe,expect,it,vi } from "vitest";
vi.mock("@/lib/instance-organization", async () => {
 const fixture = await import("@/test/installation-company");
 return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization };
});

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
import type { BalanceRow,Balances } from "@/lib/wms-ops";
import * as wms from "@/lib/wms-ops";

function row(over: Partial<BalanceRow> = {}): BalanceRow {
  return {
    organization_id: 7,
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
  asMock(wms.fetchBalances).mockReset().mockResolvedValue({ rows: [], sku_count: 0 });
});

describe("WmsBalances", () => {
  it("сужает один SKU по юрлицу, складу и партии; сброс возвращает все строки", async () => {
    render(<WmsBalances initial={{ rows: [
      row({ organization_id: 7, warehouse: "Главный", batch_ref: "A" }),
      row({ organization_id: 8, warehouse: "Главный", batch_ref: "B" }),
      row({ organization_id: 7, warehouse: "Цех", batch_ref: "C" }),
    ], sku_count: 1 }} />);
  await waitForCompany();
    await configureCompany("7");
    expect(screen.getByText("Строк: 2 из 2")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Склад остатков"), { target: { value: JSON.stringify("Цех") } });
    const table = within(screen.getByRole("table"));
    expect(table.getByText("C")).toBeInTheDocument();
    expect(table.queryByText("A")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Поиск остатков по коду, названию, ячейке или партии"), { target: { value: "B" } });
    expect(screen.getByText("Нет строк по выбранным условиям")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    expect(screen.getByText("Строк: 2 из 2")).toBeInTheDocument();
  });

  it("можно отдельно найти строки без указанного склада", async () => {
    render(<WmsBalances initial={{ rows: [row({ warehouse: "" }), row({ warehouse: "Цех" })], sku_count: 1 }} />);
  await waitForCompany();
    fireEvent.change(screen.getByLabelText("Склад остатков"), { target: { value: JSON.stringify("") } });
    expect(screen.getByText("Строк: 1 из 2")).toBeInTheDocument();
  });
  it("находит конкретную партию и ячейку среди одинаковых SKU", async () => {
    render(<WmsBalances initial={{ rows: [
      row({ location_code: "A-01", batch_ref: "П-1" }),
      row({ location_code: "C-02", batch_ref: "П-2" }),
    ], sku_count: 1 }} />);
  await waitForCompany();
    const search = screen.getByLabelText("Поиск остатков по коду, названию, ячейке или партии");
    fireEvent.change(search, { target: { value: "п-2" } });
    expect(within(screen.getByRole("table")).getByText("C-02")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).queryByText("A-01")).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "a-01" } });
    expect(within(screen.getByRole("table")).getByText("П-1")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).queryByText("П-2")).not.toBeInTheDocument();
  });
  it("shows separate owners and preserves rows when reload fails", async () => {
    asMock(wms.fetchBalances).mockRejectedValueOnce(new Error("unavailable"));
    render(<WmsBalances initial={{ rows: [row({ organization_id: 7 }), row({ organization_id: 8, qty: 2 })], sku_count: 1 }} />);
  await waitForCompany();
    expect(within(screen.getByRole("table")).getByText("Юрлицо №7")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).queryByText("Юрлицо №8")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Показаны ранее загруженные данные");
    expect(within(screen.getByRole("table")).getByText("Юрлицо №7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Обновить/ })).toBeEnabled();
  });
  it("рендерит строки остатков: код, номенклатура, склад, ячейка, партия и число", async () => {
    const initial: Balances = { rows: [row()], sku_count: 1 };
    render(<WmsBalances initial={initial} />);
  await waitForCompany();

    const table = within(screen.getByRole("table"));
    expect(table.getByText("6СТ-190")).toBeInTheDocument();
    expect(table.getByText("Аккумулятор 190Ah")).toBeInTheDocument();
    expect(table.getByText("Главный")).toBeInTheDocument();
    expect(table.getByText("A-01")).toBeInTheDocument();
    expect(table.getByText("П-1")).toBeInTheDocument();
    expect(table.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("SKU: 1")).toBeInTheDocument();
  });

  it("пустые название/ячейку/партию заменяет прочерком, положительный остаток окрашен как ink", async () => {
    const initial: Balances = {
      rows: [row({ sku_title: "", location_code: "", batch_ref: "" })],
      sku_count: 1,
    };
    render(<WmsBalances initial={initial} />);
  await waitForCompany();

    const dashes = screen.getAllByText("—");
    expect(dashes).toHaveLength(3);
    const qtyCell = screen.getByText("5");
    expect(qtyCell.className).toMatch(/text-ink/);
    expect(qtyCell.className).not.toMatch(/text-red-600/);
  });

  it("отрицательный остаток окрашен красным и форматируется по-русски (разделитель тысяч)", async () => {
    const initial: Balances = { rows: [row({ qty: -1234 })], sku_count: 1 };
    render(<WmsBalances initial={initial} />);
  await waitForCompany();

    const qtyCell = screen.getByText(
      (_content, el) => (el?.textContent ?? "").replace(/\s/g, " ") === "-1 234",
    );
    expect(qtyCell).toBeInTheDocument();
    expect(qtyCell.className).toMatch(/text-red-600/);
  });

  it("пустой список показывает заглушку «Нет строк по выбранным условиям»", async () => {
    render(<WmsBalances initial={{ rows: [], sku_count: 0 }} />);
  await waitForCompany();
    expect(
      screen.getByText("Нет строк по выбранным условиям"),
    ).toBeInTheDocument();
  });

  it("поиск по коду SKU фильтрует строки без учёта регистра", async () => {
    const initial: Balances = {
      rows: [row({ sku_code: "6СТ-190", sku_title: "Первый" }), row({ sku_code: "9СТ-77", sku_title: "Второй" })],
      sku_count: 2,
    };
    render(<WmsBalances initial={initial} />);
  await waitForCompany();

    fireEvent.change(screen.getByPlaceholderText("Код, название, ячейка или партия"), {
      target: { value: "6ст" },
    });

    expect(screen.getByText("Первый")).toBeInTheDocument();
    expect(screen.queryByText("Второй")).not.toBeInTheDocument();
  });

  it("поиск по названию SKU тоже фильтрует и при отсутствии совпадений показывает заглушку", async () => {
    const initial: Balances = {
      rows: [row({ sku_code: "6СТ-190", sku_title: "Аккумулятор" })],
      sku_count: 1,
    };
    render(<WmsBalances initial={initial} />);
  await waitForCompany();

    fireEvent.change(screen.getByPlaceholderText("Код, название, ячейка или партия"), {
      target: { value: "аккум" },
    });
    expect(screen.getByText("Аккумулятор")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Код, название, ячейка или партия"), {
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
  await waitForCompany();

    fireEvent.click(screen.getByRole("button", { name: /Обновить/ }));

    await waitFor(() => expect(wms.fetchBalances).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("НОВЫЙ")).toBeInTheDocument();
    expect(screen.getByText("SKU: 1")).toBeInTheDocument();
  });

  it("ссылка «Сверка с остатками 1С →» ведёт на /erp/wms/stock", async () => {
    render(<WmsBalances initial={{ rows: [], sku_count: 0 }} />);
  await waitForCompany();
    const link = screen.getByRole("link", { name: "Сверка с остатками 1С →" });
    expect(link).toHaveAttribute("href", "/erp/wms/stock");
  });
});

configureBeforeEach(() => resetCompany(7));
