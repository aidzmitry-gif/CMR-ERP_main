import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pageMocks = vi.hoisted(() => ({
  backendAuthHeaders: vi.fn(),
  currentRole: vi.fn(),
  fetchSkuCatalogPage: vi.fn(),
  fetchNomenclatureGroups: vi.fn(),
  fetchVatRates: vi.fn(),
}));

vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div data-testid="app-shell">{children}</div>,
}));
vi.mock("@/lib/auth-headers-server", () => ({
  backendAuthHeaders: pageMocks.backendAuthHeaders,
}));
vi.mock("@/lib/role-server", () => ({
  currentRole: pageMocks.currentRole,
}));
vi.mock("@/lib/reference-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/reference-data")>();
  return {
    ...actual,
    fetchSkuCatalogPage: pageMocks.fetchSkuCatalogPage,
    fetchNomenclatureGroups: pageMocks.fetchNomenclatureGroups,
    fetchVatRates: pageMocks.fetchVatRates,
  };
});
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

import SkuCatalogPage from "./page";
import CrmCatalogPage from "@/app/crm/catalog/page";
import { CATALOG_ROW_LIMIT } from "@/lib/reference-data";

const authHeaders = {
  Authorization: "Bearer synthetic-test-token",
  "X-User-Roles": "director",
};
const sku = {
  code: "SKU-TEST",
  title: "Тестовый товар",
  unit: "шт",
  category_id: 1,
  vat_code: "20",
};
const groups = [
  { id: 1, code: "CAT-1", name: "Тестовая группа", parent_id: null, is_active: true },
];
const vatRates = [
  { id: 1, code: "20", title: "НДС20", rate: 20, start_date: "2026-01-01", end_date: null },
];
const emptyPage = { rows: [], total: 0, offset: 0, limit: CATALOG_ROW_LIMIT };
const oneRowPage = { rows: [sku], total: 1, offset: 0, limit: CATALOG_ROW_LIMIT };

beforeEach(() => {
  vi.clearAllMocks();
  pageMocks.currentRole.mockResolvedValue("director");
  pageMocks.backendAuthHeaders.mockResolvedValue(authHeaders);
  pageMocks.fetchSkuCatalogPage.mockResolvedValue(oneRowPage);
  pageMocks.fetchNomenclatureGroups.mockResolvedValue(groups);
  pageMocks.fetchVatRates.mockResolvedValue(vatRates);
});

describe.each([
  ["ERP", SkuCatalogPage, "/erp/spravochniki/sku"],
  ["CRM", CrmCatalogPage, "/crm/catalog"],
] as const)("%s catalog page", (_name, Page, baseHref) => {
  async function renderPage(params: Record<string, string | string[] | undefined> = {}) {
    return render(await Page({ searchParams: Promise.resolve(params) }));
  }

  it("[PAGE-SUCCESS] forwards one server auth header set to the catalog and metadata loaders", async () => {
    const { container } = await renderPage();

    expect(screen.getByText("SKU-TEST")).toBeInTheDocument();
    expect(pageMocks.currentRole).toHaveBeenCalledTimes(1);
    expect(pageMocks.backendAuthHeaders).toHaveBeenCalledTimes(1);
    expect(pageMocks.backendAuthHeaders).toHaveBeenCalledWith("director");
    expect(pageMocks.fetchSkuCatalogPage).toHaveBeenCalledWith(
      { search: "", categorySubtreeId: null, offset: 0 }, "director", authHeaders,
    );
    expect(pageMocks.fetchNomenclatureGroups).toHaveBeenCalledWith({ roles: "director", strict: true }, authHeaders);
    expect(pageMocks.fetchVatRates).toHaveBeenCalledWith(undefined, "director", authHeaders, true);
    expect(container.innerHTML).not.toContain("synthetic-test-token");
    expect(screen.getByRole("link", { name: "Сбросить фильтры" })).toHaveAttribute("href", baseHref);
    expect(screen.getByRole("link", { name: "SKU-TEST" })).toHaveAttribute("href", "/erp/spravochniki/sku/SKU-TEST");
    expect(container.querySelector("form")).toHaveAttribute("action", baseHref);
    expect(screen.queryByRole("button", { name: /Перенести в счёт|Подобрать/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/АКБ 6СТ-190|В пути, шт|Минск \(центр/)).not.toBeInTheDocument();
    if (_name === "CRM") expect(screen.getByText(/Цены и остатки по складам здесь пока неизвестны/)).toBeInTheDocument();
  });

  it("[PAGE-403] renders an unavailable source after an authenticated 403", async () => {
    pageMocks.fetchSkuCatalogPage.mockRejectedValueOnce(new Error("HTTP 403"));

    await renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent("Список товаров неизвестен");
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
    expect(screen.queryByText("SKU-TEST")).not.toBeInTheDocument();
  });

  it("[PAGE-NETWORK] renders an unavailable source after a network failure", async () => {
    pageMocks.fetchSkuCatalogPage.mockRejectedValueOnce(new TypeError("offline"));

    await renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent("Список товаров неизвестен");
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
    expect(screen.queryByText("SKU-TEST")).not.toBeInTheDocument();
  });

  it("[PAGE-MALFORMED] maps strict loader failure to unavailable, not an empty catalog", async () => {
    pageMocks.fetchSkuCatalogPage.mockRejectedValueOnce(new Error("Некорректный ответ каталога номенклатуры."));

    await renderPage();

    expect(pageMocks.fetchSkuCatalogPage).toHaveBeenCalledWith(
      { search: "", categorySubtreeId: null, offset: 0 }, "director", authHeaders,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Список товаров неизвестен");
    expect(screen.queryByText("Нет данных")).not.toBeInTheDocument();
  });

  it("[PAGE-EMPTY] keeps a valid empty response distinct from unavailable", async () => {
    pageMocks.fetchSkuCatalogPage.mockResolvedValueOnce(emptyPage);
    pageMocks.fetchNomenclatureGroups.mockResolvedValueOnce([]);
    pageMocks.fetchVatRates.mockResolvedValueOnce([]);

    await renderPage();

    expect(screen.getByText("Нет данных")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Найдено 0 позиций");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("[PAGE-SKU-FILTER-STATE] carries validated GET filters and rejects duplicate or overflow values", async () => {
    pageMocks.fetchSkuCatalogPage.mockResolvedValueOnce({ ...oneRowPage, total: 251, offset: 250 });
    await renderPage({ search: "SKU-TE", category_subtree_id: "1", offset: "250" });

    expect(screen.getByLabelText("Поиск номенклатуры")).toHaveValue("SKU-TE");
    expect(screen.getByLabelText("Группа номенклатуры")).toHaveValue("1");
    expect(pageMocks.fetchSkuCatalogPage).toHaveBeenCalledWith(
      { search: "SKU-TE", categorySubtreeId: 1, offset: 250 }, "director", authHeaders,
    );

    cleanup();
    vi.clearAllMocks();
    const astralSearch = "😀".repeat(512);
    await renderPage({ search: astralSearch });
    expect(pageMocks.fetchSkuCatalogPage).toHaveBeenCalledWith(
      { search: astralSearch, categorySubtreeId: null, offset: 0 }, "director", authHeaders,
    );

    const invalid = [
      { search: ["one", "two"] },
      { offset: "2147483648" },
      { search: "x".repeat(513) },
      { search: "😀".repeat(513) },
    ];
    for (const params of invalid) {
      cleanup();
      vi.clearAllMocks();
      await renderPage(params);
      expect(screen.getByRole("alert")).toHaveTextContent("Некорректные параметры");
      expect(screen.getByRole("link", { name: "Сбросить параметры" })).toHaveAttribute("href", baseHref);
      expect(pageMocks.fetchSkuCatalogPage).not.toHaveBeenCalled();
    }
  });

  it("[PAGE-GROUPS-UNAVAILABLE] keeps SKU results while group labels stay unknown", async () => {
    pageMocks.fetchSkuCatalogPage.mockResolvedValueOnce(oneRowPage);
    pageMocks.fetchNomenclatureGroups.mockRejectedValueOnce(new Error("HTTP 503"));

    await renderPage();

    expect(screen.getByText("SKU-TEST")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("групп номенклатуры недоступен");
    expect(screen.getByText("Справочник групп недоступен")).toBeInTheDocument();
    expect(screen.queryByText("не задана")).not.toBeInTheDocument();
  });

  it("[PAGE-VAT-UNAVAILABLE] keeps SKU results while VAT labels stay unknown", async () => {
    pageMocks.fetchSkuCatalogPage.mockResolvedValueOnce(oneRowPage);
    pageMocks.fetchVatRates.mockRejectedValueOnce(new Error("HTTP 503"));

    await renderPage();

    expect(screen.getByText("SKU-TEST")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("ставок НДС недоступен");
    expect(screen.getByText("Справочник ставок НДС недоступен")).toBeInTheDocument();
    expect(screen.queryByText("нет данных")).not.toBeInTheDocument();
  });
});
