import Link from "next/link";
import { Search } from "lucide-react";

import type { NomenclatureGroup, SkuRow, VatRateRow } from "@/lib/reference-data";
import { CATALOG_ROW_LIMIT } from "@/lib/reference-data";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchNomenclatureGroups, fetchSkuCatalogPage, fetchVatRates } from "@/lib/reference-data";
import { categoryNameMap } from "@/lib/spravochniki-sku-catalog";

export type SkuCatalogBaseHref = "/erp/spravochniki/sku" | "/crm/catalog";

interface Props {
  baseHref?: SkuCatalogBaseHref;
  skus: SkuRow[];
  total: number;
  offset: number;
  search: string;
  categoryId: number | null;
  groups: NomenclatureGroup[];
  groupsUnavailable: boolean;
  vatRates: VatRateRow[];
  vatUnavailable: boolean;
  unavailable?: boolean;
  forbidden?: boolean;
}

function pageHref(baseHref: SkuCatalogBaseHref, search: string, categoryId: number | null, offset: number): string {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (categoryId !== null) params.set("category_subtree_id", String(categoryId));
  params.set("offset", String(offset));
  return `${baseHref}?${params.toString()}`;
}

/** Каталог SKU с серверной фильтрацией и страницами по лимиту structural-query. */
export function SpravSkuCatalog({
  baseHref = "/erp/spravochniki/sku",
  skus,
  total,
  offset,
  search,
  categoryId,
  groups,
  groupsUnavailable,
  vatRates,
  vatUnavailable,
  unavailable = false,
  forbidden = false,
}: Props) {
  const catNames = categoryNameMap(groups);
  const vatTitles = new Map(vatRates.map((v) => [v.code, v]));
  const activeCategories = groups
    .filter((group) => group.is_active)
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const hasNext = offset + skus.length < total;
  const hasPrevious = offset > 0;
  const isOutOfRange = total > 0 && skus.length === 0 && offset >= total;

  if (forbidden) return <section className="p-6">
    <h2 className="font-bold">Номенклатура (SKU)</h2>
    <p role="alert">Общий справочник номенклатуры недоступен с вашим рабочим доступом.</p>
  </section>;

  if (unavailable) return <section className="p-6">
    <h2 className="font-bold">Номенклатура (SKU)</h2>
    <p role="alert">Не удалось загрузить номенклатуру. Список товаров неизвестен.</p>
    <Link href={pageHref(baseHref, search, categoryId, offset)} className="text-accent underline">Повторить загрузку</Link>
    <Link href={baseHref} className="ml-3 text-accent underline">Сбросить фильтры</Link>
  </section>;

  return (
    <div className="mx-auto w-full min-w-0 max-w-[1280px] space-y-4 p-6">
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-ink">Номенклатура (SKU)</h2>
            <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
              {total} позиций
            </span>
          </div>
          <Link href="/erp/spravochniki/categories" className="text-[12px] font-medium text-accent hover:underline">
            🌳 дерево категорий
          </Link>
        </div>

        {groupsUnavailable && <p role="alert" className="mt-3 text-sm">
          Справочник групп номенклатуры недоступен; названия категорий неизвестны.
        </p>}
        {vatUnavailable && <p role="alert" className="mt-2 text-sm">
          Справочник ставок НДС недоступен; названия ставок неизвестны.
        </p>}

        <form key={JSON.stringify([baseHref, search, categoryId])} action={baseHref} method="get" className="mt-4 flex flex-wrap items-center gap-2">
          <label className="flex min-w-0 flex-1 basis-64 items-center gap-2 rounded-xl bg-sunken px-3 py-2">
            <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-faint" />
            <input
              className="w-full bg-transparent text-ink text-sm outline-none placeholder:text-faint"
              placeholder="Найти по коду или наименованию…"
              aria-label="Поиск номенклатуры"
              name="search"
              maxLength={1024}
              defaultValue={search}
            />
          </label>
          <select
            aria-label="Группа номенклатуры"
            name="category_subtree_id"
            defaultValue={categoryId === null ? "" : String(categoryId)}
            className="w-full min-w-0 max-w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20 sm:w-auto sm:max-w-96"
          >
            <option value="">Все категории</option>
            {categoryId !== null && !activeCategories.some((group) => group.id === categoryId) && (
              <option value={categoryId}>
                Категория #{categoryId} ({groupsUnavailable ? "справочник недоступен" : "название неизвестно"})
              </option>
            )}
            {activeCategories.map((group) => (
              <option key={group.id} value={group.id}>{group.name}</option>
            ))}
          </select>
          <button type="submit" className="text-sm text-accent">Найти</button>
          <Link href={baseHref} className="text-sm text-accent">Сбросить фильтры</Link>
          <span role="status" className="text-sm text-muted">
            {total === 0
              ? "Найдено 0 позиций"
              : isOutOfRange
                ? `Найдено ${total} позиций · страница вне диапазона`
                : `Найдено ${total} позиций · показаны ${offset + 1}–${Math.min(offset + skus.length, total)}`}
          </span>
        </form>

        {(hasPrevious || hasNext) && <nav aria-label="Страницы каталога" className="mt-3 flex flex-wrap gap-3 text-sm">
          {hasPrevious && <Link href={pageHref(baseHref, search, categoryId, Math.max(0, offset - CATALOG_ROW_LIMIT))}>
            Предыдущая страница
          </Link>}
          {hasNext && <Link href={pageHref(baseHref, search, categoryId, offset + CATALOG_ROW_LIMIT)}>
            Следующая страница
          </Link>}
        </nav>}
      </div>

      <div className="rounded-2xl bg-surface shadow-card">
        <div className="max-w-full overflow-x-auto">
          <table className="w-full min-w-[800px] table-fixed text-sm">
            <thead>
              <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="w-[20%] px-4 py-2 font-semibold">Код</th>
                <th className="w-[34%] px-4 py-2 font-semibold">Наименование</th>
                <th className="w-[8%] px-4 py-2 font-semibold">Ед.</th>
                <th className="w-[17%] px-4 py-2 font-semibold">Категория</th>
                <th className="w-[11%] px-4 py-2 font-semibold">НДС</th>
                <th className="w-[10%] px-4 py-2 font-semibold">Активность</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {skus.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">
                  {total > 0
                    ? isOutOfRange
                      ? <>Страница вне диапазона. <Link href={pageHref(baseHref, search, categoryId, 0)} className="text-accent underline">Первая страница</Link></>
                      : "На этой странице нет строк; перейдите на предыдущую страницу."
                    : search || categoryId !== null ? "Ничего не найдено" : "Нет данных"}
                </td></tr>
              ) : skus.map((sku) => {
                const vat = sku.vat_code ? vatTitles.get(sku.vat_code) : undefined;
                return (
                  <tr key={sku.code} className="hover:bg-sunken/60 [&>td]:align-top">
                    <td className="break-all px-4 py-2.5 font-mono text-[12px] text-muted">
                      <Link href={`/erp/spravochniki/sku/${encodeURIComponent(sku.code)}`} className="text-accent hover:underline">
                        {sku.code}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-ink" title={sku.title}>
                      <Link href={`/erp/spravochniki/sku/${encodeURIComponent(sku.code)}`} className="block break-words text-accent hover:underline">
                        {sku.title}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-muted">{sku.unit ?? "—"}</td>
                    <td className="break-words px-4 py-2.5 text-muted">
                      {sku.category_id == null ? <span className="italic text-faint">не задана</span>
                        : groupsUnavailable ? "Справочник групп недоступен"
                          : catNames.get(sku.category_id) ?? `#${sku.category_id}`}
                    </td>
                    <td className="break-words px-4 py-2.5 text-muted">
                      {sku.vat_code == null ? <span className="italic text-faint">нет данных</span>
                        : vatUnavailable ? "Справочник ставок НДС недоступен"
                          : vat ? `${vat.title} (${vat.rate}%)` : sku.vat_code}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                        Активен
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="border-t border-line px-5 py-3 text-[12px] text-muted">
          Записи архивируются, не удаляются — на них могут ссылаться документы. Клик по коду или наименованию
          открывает карточку номенклатуры (провенанс, ТН ВЭД, себестоимость, остатки).
        </div>
      </div>
    </div>
  );
}

export type SkuCatalogSearchParams = Record<string, string | string[] | undefined>;
type CatalogFilters = { search: string; categoryId: number | null; offset: number };

function oneValue(params: SkuCatalogSearchParams, key: string): { value: string | undefined; error: boolean } {
  const raw = params[key];
  if (Array.isArray(raw)) return raw.length === 1
    ? { value: raw[0], error: false }
    : { value: undefined, error: true };
  return { value: raw, error: false };
}

function parseFilters(params: SkuCatalogSearchParams): CatalogFilters | null {
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


/** Общее серверное чтение каталога: авторизация и ошибки одинаковы для ERP и CRM. */
export async function SkuCatalogContent({
  searchParams,
  baseHref = "/erp/spravochniki/sku",
}: {
  searchParams?: Promise<SkuCatalogSearchParams>;
  baseHref?: SkuCatalogBaseHref;
} = {}) {
  const filters = parseFilters(searchParams ? await searchParams : {});
  if (!filters) return <section className="p-6">
    <h2 className="font-bold">Номенклатура (SKU)</h2>
    <p role="alert">Некорректные параметры поиска или страницы каталога.</p>
    <Link href={baseHref} className="text-accent underline">Сбросить параметры</Link>
  </section>;
  return renderCatalog(filters, baseHref);
}

async function renderCatalog(filters: CatalogFilters, baseHref: SkuCatalogBaseHref) {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const [skuResult, groupsResult, vatResult] = await Promise.all([
    fetchSkuCatalogPage({
      search: filters.search,
      categorySubtreeId: filters.categoryId,
      offset: filters.offset,
    }, role, authHeaders)
      .then((page) => ({ page, unavailable: false as const, forbidden: false }))
      .catch((error: unknown) => ({
        page: null,
        unavailable: true as const,
        forbidden: error instanceof Error && error.message === "403",
      })),
    fetchNomenclatureGroups({ roles: role, strict: true }, authHeaders)
      .then((rows) => ({ rows, unavailable: false as const }))
      .catch(() => ({ rows: [], unavailable: true as const })),
    fetchVatRates(undefined, role, authHeaders, true)
      .then((rows) => ({ rows, unavailable: false as const }))
      .catch(() => ({ rows: [], unavailable: true as const })),
  ]);

  return (
    <SpravSkuCatalog
      baseHref={baseHref}
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
      forbidden={skuResult.forbidden}
    />
  );
}
