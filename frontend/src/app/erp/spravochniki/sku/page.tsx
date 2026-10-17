import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { SpravSkuCatalog } from "@/components/erp/spravochniki/sprav-sku-catalog";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import {
  fetchNomenclatureGroups,
  fetchSkuCatalogPage,
  fetchVatRates,
} from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

type SearchParams = Record<string, string | string[] | undefined>;
type CatalogFilters = { search: string; categoryId: number | null; offset: number };

function oneValue(params: SearchParams, key: string): { value: string | undefined; error: boolean } {
  const raw = params[key];
  if (Array.isArray(raw)) return raw.length === 1
    ? { value: raw[0], error: false }
    : { value: undefined, error: true };
  return { value: raw, error: false };
}

function parseFilters(params: SearchParams): CatalogFilters | null {
  const searchValue = oneValue(params, "search");
  const categoryValue = oneValue(params, "category_subtree_id");
  const offsetValue = oneValue(params, "offset");
  if (searchValue.error || categoryValue.error || offsetValue.error) return null;

  const search = searchValue.value ?? "";
  if (Array.from(search).length > 512) return null;

  let categoryId: number | null = null;
  if (categoryValue.value && !/^\d+$/.test(categoryValue.value)) return null;
  if (categoryValue.value) {
    categoryId = Number(categoryValue.value);
    if (!Number.isSafeInteger(categoryId) || categoryId < 1) return null;
  }

  let offset = 0;
  if (offsetValue.value !== undefined) {
    if (!/^\d+$/.test(offsetValue.value)) return null;
    offset = Number(offsetValue.value);
    if (!Number.isSafeInteger(offset) || offset > 2_147_483_647) return null;
  }

  return { search, categoryId, offset };
}

export default async function SkuCatalogPage({
  searchParams,
}: {
  searchParams?: Promise<SearchParams>;
} = {}) {
  const params = searchParams ? await searchParams : {};
  const filters = parseFilters(params);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Номенклатура"]}>
      {filters ? await renderCatalog(filters) : (
        <section className="p-6">
          <h2 className="font-bold">Номенклатура (SKU)</h2>
          <p role="alert">Некорректные параметры поиска или страницы каталога.</p>
          <Link href="/erp/spravochniki/sku" className="text-accent underline">
            Сбросить параметры
          </Link>
        </section>
      )}
    </AppShell>
  );
}

async function renderCatalog(filters: CatalogFilters) {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const [skuResult, groupsResult, vatResult] = await Promise.all([
    fetchSkuCatalogPage({
      search: filters.search,
      categorySubtreeId: filters.categoryId,
      offset: filters.offset,
    }, role, authHeaders)
      .then((page) => ({ page, unavailable: false as const }))
      .catch(() => ({ page: null, unavailable: true as const })),
    fetchNomenclatureGroups({ roles: role, strict: true }, authHeaders)
      .then((rows) => ({ rows, unavailable: false as const }))
      .catch(() => ({ rows: [], unavailable: true as const })),
    fetchVatRates(undefined, role, authHeaders, true)
      .then((rows) => ({ rows, unavailable: false as const }))
      .catch(() => ({ rows: [], unavailable: true as const })),
  ]);

  return (
    <SpravSkuCatalog
      skus={skuResult.page?.rows ?? []}
      total={skuResult.page?.total ?? 0}
      offset={filters.offset}
      search={filters.search}
      categoryId={filters.categoryId}
      groups={groupsResult.rows}
      groupsUnavailable={groupsResult.unavailable}
      vatRates={vatResult.rows}
      vatUnavailable={vatResult.unavailable}
      unavailable={skuResult.unavailable}
    />
  );
}
