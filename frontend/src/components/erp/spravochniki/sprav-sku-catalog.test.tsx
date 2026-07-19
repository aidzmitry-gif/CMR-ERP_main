import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (роутер App Router в тесте недоступен).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { SpravSkuCatalog } from "@/components/erp/spravochniki/sprav-sku-catalog";
import type { NomenclatureGroup, SkuRow, VatRateRow } from "@/lib/reference-data";
import { CATALOG_ROW_LIMIT } from "@/lib/reference-data";

const groups: NomenclatureGroup[] = [
  { id: 1, code: "batteries", name: "Батареи", parent_id: null, is_active: true },
  { id: 2, code: "chargers", name: "Зарядки", parent_id: null, is_active: true },
  { id: 3, code: "archived-group", name: "Архивная группа", parent_id: null, is_active: false },
];

const vatRates: VatRateRow[] = [
  { id: 1, code: "НДС20", title: "НДС", rate: 20, start_date: "2024-01-01", end_date: null },
];

const skus: SkuRow[] = [
  { code: "SKU-001", title: "Аккумулятор 18650", unit: "шт", category_id: 1, vat_code: "НДС20" },
  { code: "SKU-002", title: "Зарядное устройство USB-C", unit: "шт", category_id: 2, vat_code: null },
  { code: "SKU-003", title: "Без категории", unit: null, category_id: null, vat_code: "ЗАГАДКА" },
];

describe("SpravSkuCatalog", () => {
  it("рендерит счётчик позиций и все строки без фильтра", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    expect(screen.getByText("3 позиций")).toBeInTheDocument();
    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.getByText("Зарядное устройство USB-C")).toBeInTheDocument();
    expect(screen.getByText("Без категории")).toBeInTheDocument();
  });

  it("резолвит НДС по коду, показывает title+rate; неизвестный код печатает как есть; отсутствие — «нет данных»", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    expect(screen.getByText("НДС (20%)")).toBeInTheDocument();
    expect(screen.getByText("ЗАГАДКА")).toBeInTheDocument();
    expect(screen.getByText("нет данных")).toBeInTheDocument();
  });

  it("резолвит категорию по id и показывает «не задана» для строк без category_id", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    // "Батареи"/"Зарядки" встречаются и в select (option), и в ячейке таблицы — берём ячейку строки.
    expect(screen.getByText("SKU-001").closest("tr")).toHaveTextContent("Батареи");
    expect(screen.getByText("SKU-002").closest("tr")).toHaveTextContent("Зарядки");
    expect(screen.getByText("не задана")).toBeInTheDocument();
  });

  it("ед. измерения — тире, если unit=null", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    // SKU-003 unit=null → «—»
    const row = screen.getByText("SKU-003").closest("tr")!;
    expect(row).toHaveTextContent("—");
  });

  it("фильтр по категории в select оставляет только строки этой категории", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "1" } });

    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.queryByText("Зарядное устройство USB-C")).not.toBeInTheDocument();
    expect(screen.queryByText("Без категории")).not.toBeInTheDocument();
  });

  it("select не предлагает архивную категорию в списке опций", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    expect(screen.queryByRole("option", { name: "Архивная группа" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Батареи" })).toBeInTheDocument();
  });

  it("поиск фильтрует по коду/названию (регистронезависимо) и показывает «Ничего не найдено»", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    const search = screen.getByPlaceholderText("Найти по коду или наименованию…");

    fireEvent.change(search, { target: { value: "зарядное" } });
    expect(screen.getByText("Зарядное устройство USB-C")).toBeInTheDocument();
    expect(screen.queryByText("Аккумулятор 18650")).not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "нет-такого-zzz" } });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("пустой список skus без фильтра показывает «Нет данных»", () => {
    render(<SpravSkuCatalog skus={[]} groups={groups} vatRates={vatRates} />);
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });

  it("ссылка на карточку SKU кодирует код в href", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    const link = screen.getByRole("link", { name: "SKU-001" });
    expect(link).toHaveAttribute("href", "/erp/spravochniki/sku/SKU-001");
  });

  it("при достижении потолка запроса показывает «+» и предупреждение", () => {
    const capSkus: SkuRow[] = Array.from({ length: CATALOG_ROW_LIMIT }, (_, i) => ({
      code: `SKU-${i}`,
      title: `Товар ${i}`,
      unit: "шт",
      category_id: null,
      vat_code: null,
    }));
    render(<SpravSkuCatalog skus={capSkus} groups={groups} vatRates={vatRates} />);
    expect(screen.getByText(`${CATALOG_ROW_LIMIT}+ позиций`)).toBeInTheDocument();
    expect(
      screen.getByText(/Показаны первые 250 позиций \(потолок одного запроса\)/),
    ).toBeInTheDocument();
  });

  it("ниже потолка запроса предупреждение не показывается", () => {
    render(<SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />);
    expect(screen.queryByText(/потолок одного запроса/)).not.toBeInTheDocument();
  });
});
