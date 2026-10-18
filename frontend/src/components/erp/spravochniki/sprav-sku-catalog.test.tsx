import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/link → простая <a> в jsdom (роутер App Router в тесте недоступен).
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: vi.fn() }));
vi.mock("@/lib/role-server", () => ({ currentRole: vi.fn() }));

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

const baseProps = {
  skus,
  total: skus.length,
  offset: 0,
  search: "",
  categoryId: null,
  groups,
  groupsUnavailable: false,
  vatRates,
  vatUnavailable: false,
  unavailable: false,
};

function renderCatalog(props: Partial<typeof baseProps> = {}) {
  return render(<SpravSkuCatalog {...baseProps} {...props} />);
}

describe("SpravSkuCatalog", () => {
  it("renders the server-filtered subtree result and current combined filter values", () => {
    const child: SkuRow = { ...skus[0], code: "CHILD", category_id: 4 };
    renderCatalog({
      skus: [child],
      total: 1,
      search: "18650 CHILD",
      categoryId: 1,
      groups: [...groups, { id: 4, code: "li", name: "Литиевые", parent_id: 1, is_active: true }],
    });

    expect(screen.getByText("CHILD")).toBeInTheDocument();
    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveValue("18650 CHILD");
    expect(screen.getByLabelText("Группа номенклатуры")).toHaveValue("1");
    expect(screen.getByRole("link", { name: "Сбросить фильтры" })).toHaveAttribute("href", "/erp/spravochniki/sku");
    expect(screen.getByRole("status")).toHaveTextContent("Найдено 1 позиций");
  });

  it("shows an unavailable source rather than an empty catalog", () => {
    renderCatalog({ skus: [], total: 0, search: "A %_ B", categoryId: 3, offset: 250, unavailable: true });
    expect(screen.getByRole("alert")).toHaveTextContent("Список товаров неизвестен");
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Повторить загрузку" })).toHaveAttribute(
      "href", "/erp/spravochniki/sku?search=A+%25_+B&category_subtree_id=3&offset=250",
    );
    expect(screen.getByRole("link", { name: "Сбросить фильтры" })).toHaveAttribute("href", "/erp/spravochniki/sku");
  });

  it("рендерит точный счётчик и строки текущей страницы", () => {
    renderCatalog();
    expect(screen.getByText("3 позиций")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Найдено 3 позиций · показаны 1–3");
    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.getByText("Зарядное устройство USB-C")).toBeInTheDocument();
    expect(screen.getByText("Без категории")).toBeInTheDocument();
  });

  it("резолвит НДС по коду, показывает title+rate; неизвестный код печатает как есть; отсутствие — «нет данных»", () => {
    renderCatalog();
    expect(screen.getByText("НДС (20%)")).toBeInTheDocument();
    expect(screen.getByText("ЗАГАДКА")).toBeInTheDocument();
    expect(screen.getByText("нет данных")).toBeInTheDocument();
  });

  it("резолвит категорию по id и показывает «не задана» для строк без category_id", () => {
    renderCatalog();
    expect(screen.getByText("SKU-001").closest("tr")).toHaveTextContent("Батареи");
    expect(screen.getByText("SKU-002").closest("tr")).toHaveTextContent("Зарядки");
    expect(screen.getByText("не задана")).toBeInTheDocument();
  });

  it("ед. измерения — тире, если unit=null", () => {
    renderCatalog();
    const row = screen.getByText("SKU-003").closest("tr")!;
    expect(row).toHaveTextContent("—");
  });

  it("select показывает категорию текущего серверного результата", () => {
    renderCatalog({ skus: [skus[0]], total: 1, categoryId: 1 });
    expect(screen.getByLabelText("Группа номенклатуры")).toHaveValue("1");
    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.queryByText("Зарядное устройство USB-C")).not.toBeInTheDocument();
    expect(screen.queryByText("Без категории")).not.toBeInTheDocument();
  });

  it("select не предлагает архивную категорию в списке опций", () => {
    renderCatalog();
    expect(screen.queryByRole("option", { name: "Архивная группа" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Батареи" })).toBeInTheDocument();
  });

  it("search field carries the current server-filtered result and shows no match state", () => {
    const { unmount } = renderCatalog({ skus: [skus[1]], total: 1, search: "зарядное" });
    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveValue("зарядное");
    expect(screen.getByText("Зарядное устройство USB-C")).toBeInTheDocument();
    expect(screen.queryByText("Аккумулятор 18650")).not.toBeInTheDocument();
    unmount();

    renderCatalog({ skus: [], total: 0, search: "нет-такого-zzz" });
    expect(screen.getByText("Ничего не найдено")).toBeInTheDocument();
  });

  it("пустой список без фильтра показывает «Нет данных»", () => {
    renderCatalog({ skus: [], total: 0 });
    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });

  it("ссылка на карточку SKU кодирует код в href", () => {
    renderCatalog();
    const link = screen.getByRole("link", { name: "SKU-001" });
    expect(link).toHaveAttribute("href", "/erp/spravochniki/sku/SKU-001");
  });

  it("при достижении лимита страницы показывает полный total и следующую страницу", () => {
    const pageSkus: SkuRow[] = Array.from({ length: CATALOG_ROW_LIMIT }, (_, i) => ({
      code: `SKU-${i}`,
      title: `Товар ${i}`,
      unit: "шт",
      category_id: null,
      vat_code: null,
    }));
    renderCatalog({ skus: pageSkus, total: CATALOG_ROW_LIMIT + 1 });
    expect(screen.getByText(`${CATALOG_ROW_LIMIT + 1} позиций`)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Следующая страница" })).toHaveAttribute(
      "href", `/erp/spravochniki/sku?offset=${CATALOG_ROW_LIMIT}`,
    );
    expect(screen.queryByText(/потолок одного запроса/)).not.toBeInTheDocument();
  });

  it("ниже лимита страницы навигация не показывается", () => {
    renderCatalog();
    expect(screen.queryByRole("navigation", { name: "Страницы каталога" })).not.toBeInTheDocument();
  });

  it("[UI-SKU-GET-FILTERS] submits search and category through native GET without retaining offset", () => {
    renderCatalog({ search: "A %_ B", categoryId: 1, offset: 250 });
    const form = screen.getByLabelText("Поиск номенклатуры").closest("form");
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/erp/spravochniki/sku");
    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveAttribute("name", "search");
    // HTML maxlength counts UTF-16 units; 1024 units can represent 512 Unicode code points.
    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveAttribute("maxlength", "1024");
    expect(screen.getByLabelText("Группа номенклатуры")).toHaveAttribute("name", "category_subtree_id");
    expect(form?.querySelector('[name="offset"]')).toBeNull();
  });

  it("[UI-SKU-PAGING-FILTERS] preserves encoded search and category on previous and next links", () => {
    const pageSkus = Array.from({ length: CATALOG_ROW_LIMIT }, (_, index) => ({
      code: `SKU-${index}`, title: `Товар ${index}`, unit: "шт", category_id: 1, vat_code: null,
    }));
    const { unmount } = renderCatalog({ skus: pageSkus, total: 501, offset: 250, search: "A %_ B", categoryId: 1 });
    const previous = screen.getByRole("link", { name: "Предыдущая страница" });
    const next = screen.getByRole("link", { name: "Следующая страница" });
    expect(previous).toHaveAttribute("href", "/erp/spravochniki/sku?search=A+%25_+B&category_subtree_id=1&offset=0");
    expect(next).toHaveAttribute("href", "/erp/spravochniki/sku?search=A+%25_+B&category_subtree_id=1&offset=500");

    unmount();
    renderCatalog({ skus: [], total: 301, offset: 500, search: "A %_ B", categoryId: 1 });
    expect(screen.getByRole("status")).toHaveTextContent("Найдено 301 позиций · страница вне диапазона");
    expect(screen.getByRole("status")).not.toHaveTextContent("показаны 501–301");
    expect(screen.getByRole("link", { name: "Первая страница" })).toHaveAttribute(
      "href", "/erp/spravochniki/sku?search=A+%25_+B&category_subtree_id=1&offset=0",
    );
  });

  it("[UI-SKU-METADATA-UNKNOWN] keeps unavailable group and VAT metadata distinct from missing values", () => {
    const { unmount } = renderCatalog({ groups: [], groupsUnavailable: true, vatRates: [], vatUnavailable: true, categoryId: 99 });
    expect(screen.getByText("Справочник групп номенклатуры недоступен; названия категорий неизвестны.")).toHaveAttribute("role", "alert");
    expect(screen.getByText("Справочник ставок НДС недоступен; названия ставок неизвестны.")).toHaveAttribute("role", "alert");
    expect(screen.getByRole("option", { name: "Категория #99 (справочник недоступен)" })).toHaveValue("99");

    const skuWithUnknownMetadata = within(screen.getByRole("row", { name: /SKU-001/ }));
    expect(skuWithUnknownMetadata.getByText("Справочник групп недоступен")).toBeInTheDocument();
    expect(skuWithUnknownMetadata.getByText("Справочник ставок НДС недоступен")).toBeInTheDocument();

    expect(within(screen.getByRole("row", { name: /SKU-003/ })).getByText("не задана")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /SKU-002/ })).getByText("нет данных")).toBeInTheDocument();

    unmount();
    renderCatalog({ categoryId: 99 });
    expect(screen.getByRole("option", { name: "Категория #99 (название неизвестно)" })).toHaveValue("99");
  });
});


describe("CRM catalog navigation", () => {
  it("keeps encoded filters on previous and next CRM pages", () => {
    const rows = Array.from({ length: CATALOG_ROW_LIMIT }, (_, i) => ({ ...skus[0], code: `S-${i}` }));
    render(<SpravSkuCatalog {...baseProps} skus={rows} baseHref="/crm/catalog" search="A %_ B" categoryId={1} offset={250} total={501} />);
    expect(screen.getByRole("link", { name: "Предыдущая страница" })).toHaveAttribute("href", "/crm/catalog?search=A+%25_+B&category_subtree_id=1&offset=0");
    expect(screen.getByRole("link", { name: "Следующая страница" })).toHaveAttribute("href", "/crm/catalog?search=A+%25_+B&category_subtree_id=1&offset=500");
  });

  it("retries a failed CRM source with its filters rather than showing zero stock", () => {
    render(<SpravSkuCatalog {...baseProps} baseHref="/crm/catalog" skus={[]} total={0} search="A B" categoryId={1} offset={250} unavailable />);
    expect(screen.getByRole("alert")).toHaveTextContent("Список товаров неизвестен");
    expect(screen.getByRole("link", { name: "Повторить загрузку" })).toHaveAttribute("href", "/crm/catalog?search=A+B&category_subtree_id=1&offset=250");
    expect(screen.getByRole("link", { name: "Сбросить фильтры" })).toHaveAttribute("href", "/crm/catalog");
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
  });

  it("offers the first CRM page for an out-of-range offset", () => {
    render(<SpravSkuCatalog {...baseProps} baseHref="/crm/catalog" skus={[]} total={1} search="A B" categoryId={1} offset={250} />);
    expect(screen.getByRole("status")).toHaveTextContent("страница вне диапазона");
    expect(screen.getByRole("link", { name: "Первая страница" })).toHaveAttribute("href", "/crm/catalog?search=A+B&category_subtree_id=1&offset=0");
  });

  it("searches within CRM from the first page and preserves canonical SKU detail links", () => {
    const { container } = render(<SpravSkuCatalog {...baseProps} baseHref="/crm/catalog" search="A" categoryId={1} offset={250} total={253} />);
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("action", "/crm/catalog");
    expect(form).toHaveAttribute("method", "get");
    expect(form.querySelector('[name="offset"]')).toBeNull();
    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveValue("A");
    expect(screen.getByLabelText("Группа номенклатуры")).toHaveValue("1");
    expect(screen.getByRole("link", { name: "Сбросить фильтры" })).toHaveAttribute("href", "/crm/catalog");
    expect(screen.getByRole("link", { name: "SKU-001" })).toHaveAttribute("href", "/erp/spravochniki/sku/SKU-001");
  });
});
