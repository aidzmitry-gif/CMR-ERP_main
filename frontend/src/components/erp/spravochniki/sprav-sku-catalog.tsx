"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { NomenclatureGroup, SkuRow, VatRateRow } from "@/lib/reference-data";
import { CATALOG_ROW_LIMIT } from "@/lib/reference-data";
import { categoryNameMap, filterSkusByCategory, filterSkusBySearch } from "@/lib/spravochniki-sku-catalog";

interface Props {
  skus: SkuRow[];
  groups: NomenclatureGroup[];
  vatRates: VatRateRow[];
}

/** Каталог SKU (232 реальных позиции из 1С): таблица код/название/ед./категория/НДС/активность
 * + поиск + фильтр по категории. Хаб → сюда → карточка `/erp/spravochniki/sku/[code]`. */
export function SpravSkuCatalog({ skus, groups, vatRates }: Props) {
  const [search, setSearch] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);

  const catNames = useMemo(() => categoryNameMap(groups), [groups]);
  const vatTitles = useMemo(() => new Map(vatRates.map((v) => [v.code, v])), [vatRates]);

  // Только активные категории с товарами показываем в фильтре (не засорять список архивом).
  const activeCategories = useMemo(
    () => groups.filter((g) => g.is_active).sort((a, b) => a.name.localeCompare(b.name, "ru")),
    [groups],
  );

  const filtered = useMemo(() => {
    const byCategory = filterSkusByCategory(skus, categoryId);
    return filterSkusBySearch(byCategory, search);
  }, [skus, categoryId, search]);

  const atCap = skus.length >= CATALOG_ROW_LIMIT;

  return (
    // min-w-0 — без него флекс-цепочка AppShell (overflow-y-auto без overflow-x) растягивает
    // контейнер под ширину таблицы вместо горизонтального скролла внутри неё (узкий вьюпорт:
    // 6 колонок + длинные названия 1С рвут вёрстку без этого).
    <div className="mx-auto min-w-0 max-w-[1280px] space-y-4 p-6">
      {/* Заголовок + счётчик */}
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold text-ink">Номенклатура (SKU)</h2>
            <span className="rounded-full bg-sunken px-2 py-0.5 font-mono text-[11px] text-muted">
              схема: public
            </span>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
              из 1С
            </span>
            <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
              {skus.length}
              {atCap ? "+" : ""} позиций
            </span>
          </div>
          <Link
            href="/erp/spravochniki/categories"
            className="text-[12px] font-medium text-accent hover:underline"
          >
            🌳 дерево категорий
          </Link>
        </div>

        {/* Тулбар: поиск + фильтр по категории */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="flex min-w-[260px] flex-1 items-center gap-2 rounded-xl bg-sunken px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-faint" />
            <input
              className="w-full bg-transparent text-ink text-sm outline-none placeholder:text-faint"
              placeholder="Найти по коду или наименованию…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            value={categoryId ?? ""}
            onChange={(e) => setCategoryId(e.target.value === "" ? null : Number(e.target.value))}
            className="rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
          >
            <option value="">Все категории</option>
            {activeCategories.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </div>

        {atCap && (
          <p className="mt-2 text-[11px] text-faint">
            Показаны первые {skus.length} позиций (потолок одного запроса) — растёт вместе с
            каталогом, дальше потребуется пагинация.
          </p>
        )}
      </div>

      {/* Таблица */}
      <div className="rounded-2xl bg-surface shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="px-4 py-2 font-semibold">Код</th>
                <th className="px-4 py-2 font-semibold">Наименование</th>
                <th className="px-4 py-2 font-semibold">Ед.</th>
                <th className="px-4 py-2 font-semibold">Категория</th>
                <th className="px-4 py-2 font-semibold">НДС</th>
                <th className="px-4 py-2 font-semibold">Активность</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted">
                    {search || categoryId !== null ? "Ничего не найдено" : "Нет данных"}
                  </td>
                </tr>
              ) : (
                filtered.map((s) => {
                  const vat = s.vat_code ? vatTitles.get(s.vat_code) : undefined;
                  return (
                    <tr key={s.code} className="hover:bg-sunken/60">
                      <td className="px-4 py-2.5 font-mono text-[12px] text-muted">
                        <Link
                          href={`/erp/spravochniki/sku/${encodeURIComponent(s.code)}`}
                          className="text-accent hover:underline"
                        >
                          {s.code}
                        </Link>
                      </td>
                      <td className="max-w-[420px] px-4 py-2.5 text-ink" title={s.title}>
                        <span className="block break-words">{s.title}</span>
                      </td>
                      <td className="px-4 py-2.5 text-muted">{s.unit ?? "—"}</td>
                      <td className="px-4 py-2.5 text-muted">
                        {s.category_id != null ? (
                          (catNames.get(s.category_id) ?? `#${s.category_id}`)
                        ) : (
                          <span className="italic text-faint">не задана</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-muted">
                        {vat ? `${vat.title} (${vat.rate}%)` : s.vat_code ? s.vat_code : (
                          <span className="italic text-faint">нет данных</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                          Активен
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <div className="border-t border-line px-5 py-3 text-[12px] text-muted">
          Записи архивируются, не удаляются — на них могут ссылаться документы. Клик по коду
          открывает карточку номенклатуры (провенанс, ТН ВЭД, себестоимость, остатки).
        </div>
      </div>
    </div>
  );
}
