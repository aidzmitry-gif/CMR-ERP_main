"use client";

import { Plus, Receipt, RefreshCw, Search, ShoppingCart, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  addDealItem,
  createPriceQuote,
  fetchLastOrder,
  fetchStock,
  issueDocument,
  updateDeal,
  type SkuOption,
} from "@/lib/api";
// Чистая доменная логика подбора (агрегация остатков/срок/маржа) живёт в src/lib/stock.ts
// с юнит-тестами (конвенция frontend/CLAUDE.md); здесь — только UI-обёртка.
import { aggregateStock, groupStockBySku, marginOf, srokOf, type SkuStock, type SkuWarehouseStock } from "@/lib/stock";
import { presetDateISO } from "@/lib/sales-stages";
import { useCurrency } from "./currency-context";

/** Слайс 6 (A): текст авто-назначенного следующего шага после выставления счёта — тот же,
 *  что в drawer-preview/CardMenu/call-window.tsx. */
const INVOICE_NEXT_STEP = "Проверить оплату счёта";

/**
 * Подбор товара — общая логика/UI для окна звонка (call-window.tsx, встроенная колонка)
 * и модалки подбора из сокращённой сделки (deal-drawer-preview.tsx). Вынесено из
 * call-window.tsx, где раньше жило только там (см. память mockup-reuse-canonical-shell —
 * пикер по мотивам sales-deal-picker.html, упрощённый под уже рабочий стек без дерева категорий).
 */

export interface PickerRow {
  /** Локальное намерение добавить строку; одинаковые SKU могут быть разными строками. */
  clientKey: string;
  skuId: number;
  code: string;
  title: string;
  unit: string;
  qty: number;
  picked: boolean;
  /** Цена клиенту, отредактированная вручную (попап «Ввод количества и цены» в
   *  CatalogPickerModal) — перебивает цену строки. undefined = без правки, null = цена не подтверждена. */
  priceOverride?: number | null;
  /** Согласованная цена повторяемой строки; null нельзя заменять текущей складской ценой. */
  unitPrice?: number | null;
}

interface PickerCommand {
  key: string;
  scope: string | undefined;
  dealId: string;
  row: PickerRow;
  price: number | null;
  counterparty: string;
  state: "in-flight" | "unknown" | "confirmed";
  promise?: Promise<boolean>;
  quoteStarted: boolean;
}

const UNCONFIRMED_ITEMS = "Сохранение части позиций не подтверждено. Повторите перенос: уже сохранённые позиции повторно не добавятся. До подтверждения не меняйте и не закрывайте подбор.";

/**
 * Стейт подбора: справочник+остатки (грузятся при `active`), строки корзины, поиск,
 * повтор прошлого заказа, добавление в сделку. `active` — грузить данные только когда
 * пикер реально открыт (окно звонка/модалка), а не всегда в фоне.
 */
export function useProductPicker(active: boolean, refetchKey?: string) {
  const [skus, setSkus] = useState<SkuOption[]>([]);
  /** loading → ready | auth (401/403) | error. Пустой [] больше не маскируем под «Загрузка…». */
  const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "auth" | "error">("loading");
  const [stock, setStock] = useState<Record<string, SkuStock & { unitPrice?: number | null }>>({});
  // Per-warehouse разбивка (не агрегат) — попап «Ввод количества и цены»
  // (CatalogPickerModal, catalog-picker-modal.tsx): Остаток/Резерв/Свободно по каждому складу.
  const [warehouseStock, setWarehouseStock] = useState<Record<string, SkuWarehouseStock>>({});
  const [rows, setRows] = useState<PickerRow[]>([]);
  const [query, setQuery] = useState("");
  // rowsRef — свежий снимок корзины для repeatLastOrder (дедуп по актуальным строкам);
  // genRef — «поколение» контекста: reset() его двигает, поздний async сверяет и не всыпает
  // позиции чужого контрагента, если окно звонка успело переключиться на другую сделку.
  const rowsRef = useRef(rows);
  useLayoutEffect(() => { rowsRef.current = rows; }, [rows]);
  const genRef = useRef(0);
  const commands = useRef(new Map<string, PickerCommand>());
  const scopeRef = useRef({ key: refetchKey, version: 0 });
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [submittedPrices, setSubmittedPrices] = useState<Record<string, number | null>>({});
  const [pendingDiscountApprovals, setPendingDiscountApprovals] = useState<Record<string, true>>({});
  const setDiscountApproval = useCallback((dealId: string, pending: boolean) => {
    setPendingDiscountApprovals((current) => {
      const next = { ...current };
      if (pending) next[dealId] = true;
      else delete next[dealId];
      return next;
    });
  }, []);

  // Старые неподтверждённые команды остаются в этом hook; новый контекст их не получает.
  // После возврата в прежний контекст восстанавливаем их точные снимки для повтора.
  // Атомарный сброс при смене внешнего контекста; снимки незавершённых сетевых команд сохраняются.
  useLayoutEffect(() => {
    if (scopeRef.current.key !== refetchKey) {
      scopeRef.current = { key: refetchKey, version: scopeRef.current.version + 1 };
    }
    genRef.current++;
    const retained = [...commands.current.values()].filter((c) => c.scope === refetchKey && c.state !== "confirmed");
    setRows(retained.map((c) => c.row));
    setQuery("");
    setSubmittedPrices(Object.fromEntries(retained.map((c) => [c.row.clientKey, c.price])));
    setSaveNotice(retained.some((c) => c.state !== "confirmed") ? UNCONFIRMED_ITEMS : null);
  }, [refetchKey]);

  function hasUnconfirmed(dealId?: string) {
    return [...commands.current.values()].some((c) => c.scope === scopeRef.current.key
      && (!dealId || c.dealId === dealId) && (c.state !== "confirmed" || !!c.promise));
  }
  function canClose() {
    if (!hasUnconfirmed()) return true;
    setSaveNotice(UNCONFIRMED_ITEMS);
    return false;
  }
  function canIssueInvoice(dealId: string) {
    return !hasUnconfirmed(dealId) && rowsRef.current.filter((r) => r.picked).every((r) => {
      const command = commands.current.get(r.clientKey);
      return command?.state === "confirmed" && command.dealId === dealId;
    });
  }
  function editable(row: PickerRow) {
    const command = commands.current.get(row.clientKey);
    if (!command || (command.state === "confirmed" && !command.promise)) return true;
    setSaveNotice(UNCONFIRMED_ITEMS);
    return false;
  }
  function valuesEditable(row: PickerRow) {
    if (!editable(row)) return false;
    if (!commands.current.has(row.clientKey)) return true;
    setSaveNotice("Позиция уже сохранена. Измените её в сделке; для дополнительного количества добавьте новую позицию отдельно.");
    return false;
  }

  // refetchKey (id открытой сделки/лида) в deps: остатки/цены перезагружаются и при прямой
  // смене контекста звонка (сделка→сделка без промежуточного закрытия), а не только по active.
  useEffect(() => {
    if (!active) return;
    let alive = true;
    setCatalogStatus("loading");
    setSkus([]);
    void (async () => {
      try {
        const res = await fetch("/api/sales/skus?for_picker=1", { cache: "no-store" });
        if (!alive) return;
        if (res.status === 401 || res.status === 403) {
          setSkus([]);
          setCatalogStatus("auth");
          return;
        }
        if (!res.ok) {
          setSkus([]);
          setCatalogStatus("error");
          return;
        }
        setSkus((await res.json()) as SkuOption[]);
        setCatalogStatus("ready");
      } catch {
        if (alive) {
          setSkus([]);
          setCatalogStatus("error");
        }
      }
    })();
    void fetchStock().then((stockRows) => {
      if (alive) {
        const aggregated = aggregateStock(stockRows);
        setStock(Object.fromEntries(Object.entries(aggregated).map(([code, item]) => [code, {
          ...item,
          // aggregateStock использует 0 для итогов, даже если raw-цена отсутствовала.
          unitPrice: stockRows.some((r) => r.sku_code === code && typeof r.price === "number"
            && Number.isFinite(r.price) && r.price >= 0 && r.price === item.price) ? item.price : null,
        }])));
        setWarehouseStock(groupStockBySku(stockRows));
      }
    });
    return () => {
      alive = false;
    };
  }, [active, refetchKey]);

  const inOrder = new Set(rows.map((r) => r.skuId));
  const candidates = skus
    .filter((s) => !inOrder.has(s.id))
    .filter((s) =>
      query.trim()
        ? `${s.title} ${s.code}`.toLowerCase().includes(query.trim().toLowerCase())
        : true,
    )
    .slice(0, 6);

  function addSku(s: SkuOption) {
    setRows((r) => [
      ...r,
      { clientKey: crypto.randomUUID(), skuId: s.id, code: s.code, title: s.title, unit: s.unit, qty: 1, picked: true },
    ]);
    setQuery("");
  }
  /** Добавить с явным кол-вом (CatalogPickerModal — попап «Ввод количества и цены»);
   *  повторный подбор уже добавленной позиции суммирует количество, не дублирует строку. */
  function addSkuWithQty(s: SkuOption, qty: number, priceOverride?: number | null) {
    const current = rowsRef.current.find((x) => x.skuId === s.id);
    if (current && !editable(current)) return false;
    setRows((r) => {
      const existing = r.find((x) => x.skuId === s.id);
      if (existing && !commands.current.has(existing.clientKey)) {
        return r.map((x) => (x === existing ? { ...x, qty: x.qty + qty, picked: true,
          ...(priceOverride !== undefined ? { priceOverride } : {}) } : x));
      }
      return [...r, { clientKey: crypto.randomUUID(), skuId: s.id, code: s.code, title: s.title, unit: s.unit, qty, picked: true, priceOverride }];
    });
    return true;
  }
  function setRowQty(row: PickerRow, qty: number, priceOverride?: number | null) {
    if (!valuesEditable(row)) return false;
    setRows((r) => r.map((x) => (x === row ? { ...x, qty: Math.max(1, qty),
      ...(priceOverride !== undefined ? { priceOverride } : {}) } : x)));
    return true;
  }
  /** Ручная правка цены строки (попап «Ввод количества и цены»). undefined — вернуть цену со склада. */
  function setRowPrice(skuId: number, price: number | null | undefined) {
    if (rowsRef.current.filter((r) => r.skuId === skuId).some((r) => !valuesEditable(r))) return;
    setRows((r) => r.map((x) => (x.skuId === skuId ? { ...x, priceOverride: price } : x)));
  }
  function toggleRow(row: PickerRow) {
    if (!editable(row)) return;
    setRows((r) => r.map((x) => (x === row ? { ...x, picked: !x.picked } : x)));
  }
  function removeRow(row: PickerRow) {
    if (!editable(row)) return;
    setRows((r) => r.filter((x) => x !== row));
  }
  /** Убирает только успешно отправленные снимки строк, включая отдельные строки одного SKU. */
  function removeCommittedRows(committedRows: PickerRow[]) {
    const confirmed = new Set(committedRows.filter((r) => commands.current.get(r.clientKey)?.state === "confirmed")
      .map((r) => r.clientKey));
    setRows((r) => r.filter((x) => !confirmed.has(x.clientKey)));
    for (const key of confirmed) commands.current.delete(key);
  }
  const reset = useCallback(() => {
    if ([...commands.current.values()].some((c) => c.scope === scopeRef.current.key
      && (c.state !== "confirmed" || !!c.promise))) {
      setSaveNotice(UNCONFIRMED_ITEMS);
      return false;
    }
    genRef.current++;
    scopeRef.current = { ...scopeRef.current, version: scopeRef.current.version + 1 };
    setRows([]);
    setQuery("");
    setSaveNotice(null);
    setSubmittedPrices({});
    for (const [key, command] of commands.current) {
      if (command.scope === scopeRef.current.key) commands.current.delete(key);
    }
    return true;
  }, []);

  /** Повторить прошлый заказ: подтянуть позиции последней сделки того же контрагента
   * (backend резолвит «последнюю» сам — GET /deals/{id}/repeat-last-order). Не дублирует
   * уже добавленные строки. Возвращает число РЕАЛЬНО добавленных позиций (не подтянутых:
   * если часть уже в корзине — они не считаются, чтобы тост не завышал). */
  async function repeatLastOrder(dealId: string): Promise<number> {
    const gen = genRef.current;
    const items = await fetchLastOrder(dealId);
    // Контекст сменился, пока грузили (reset двинул поколение) — не всыпать позиции чужого
    // контрагента в корзину уже другого звонка.
    if (genRef.current !== gen || !items.length) return 0;
    const existing = new Set(rowsRef.current.map((x) => x.skuId));
    const added = items.filter((it) => !existing.has(it.sku_id));
    if (added.length) {
      setRows((r) => [
        ...r,
        ...added.map((it) => ({
          clientKey: crypto.randomUUID(),
          skuId: it.sku_id,
          code: it.code,
          title: it.title,
          unit: it.unit,
          qty: Math.max(1, Math.round(it.qty)),
          picked: true,
          unitPrice: it.unit_price ?? null,
        })),
      ]);
    }
    return added.length;
  }

  // Цена строки клиенту: отредактированная вручную — приоритетнее цены со склада.
  const agreedPriceOf = (r: PickerRow) => Object.prototype.hasOwnProperty.call(submittedPrices, r.clientKey)
    ? submittedPrices[r.clientKey] : r.priceOverride !== undefined
      ? r.priceOverride : r.unitPrice !== undefined ? r.unitPrice : stock[r.code]?.unitPrice ?? null;
  const priceOf = (r: PickerRow) => agreedPriceOf(r) ?? 0;

  const pickedRows = rows.filter((r) => r.picked);
  const orderTotal = pickedRows.reduce((sum, r) => sum + priceOf(r) * r.qty, 0);
  // Себес/маржа — ТОЛЬКО по позициям «в наличии» (себес из 1С); под-заказ — предрасчёт (позже).
  const costedRows = pickedRows.filter((r) => stock[r.code]?.cost != null);
  const costedRevenue = costedRows.reduce((s, r) => s + priceOf(r) * r.qty, 0);
  const orderCost = costedRows.reduce((s, r) => s + (stock[r.code]?.cost ?? 0) * r.qty, 0);
  const orderMargin = costedRevenue - orderCost;
  const hasUnderOrder = pickedRows.some((r) => stock[r.code]?.cost == null);

  /** Согласованная цена сохраняется вместе с позицией; котировки — только история. */
  async function commitToDeal(dealId: string, counterparty: string): Promise<{ ok: number; total: number; successfulRows: PickerRow[] }> {
    const context = scopeRef.current;
    const batch = rowsRef.current.filter((r) => r.picked);
    const results = await Promise.allSettled(batch.map((row) => {
      let command = commands.current.get(row.clientKey);
      if (command && (command.dealId !== dealId || command.scope !== context.key)) return Promise.resolve(false);
      if (!command) {
        command = { key: crypto.randomUUID(), scope: context.key, dealId, row: { ...row },
          price: agreedPriceOf(row), counterparty, state: "unknown", quoteStarted: false };
        commands.current.set(row.clientKey, command);
        const frozenPrice = command.price;
        setSubmittedPrices((prices) => ({ ...prices, [row.clientKey]: frozenPrice }));
      }
      if (command.state === "confirmed") return Promise.resolve(true);
      if (command.promise) return command.promise;
      const captured = command;
      captured.state = "in-flight";
      captured.promise = (async () => {
        try {
          const ok = await addDealItem(captured.dealId, captured.row.skuId,
            captured.row.qty, captured.price, captured.key);
          captured.state = ok ? "confirmed" : "unknown";
          if (ok && !captured.quoteStarted) {
            captured.quoteStarted = true;
            if (captured.price != null) {
              try {
                await createPriceQuote(captured.row.code, captured.counterparty, captured.price);
              } catch {
                // История цены не меняет подтверждённый результат сохранения позиции.
              }
            }
          }
          return ok;
        } catch {
          captured.state = "unknown";
          return false;
        } finally {
          captured.promise = undefined;
        }
      })();
      return captured.promise;
    }));
    const successfulRows = batch.filter((_, index) => {
      const result = results[index];
      return result.status === "fulfilled" && result.value;
    });
    if (scopeRef.current === context) setSaveNotice(successfulRows.length === batch.length ? null : UNCONFIRMED_ITEMS);
    // Вызывающая сторона решает, убрать ли успешные строки: остальные callers сохраняют свою корзину.
    return { ok: successfulRows.length, total: batch.length, successfulRows };
  }

  return {
    skus,
    contextKey: refetchKey,
    pendingDiscountApprovals,
    setDiscountApproval,
    saveNotice,
    hasUnconfirmed,
    canClose,
    canIssueInvoice,
    contextToken: () => scopeRef.current,
    isCurrentContext: (token: object) => scopeRef.current === token,
    catalogStatus,
    stock,
    warehouseStock,
    rows,
    query,
    setQuery,
    candidates,
    addSku,
    addSkuWithQty,
    setRowQty,
    setRowPrice,
    toggleRow,
    removeRow,
    removeCommittedRows,
    reset,
    repeatLastOrder,
    pickedRows,
    orderTotal,
    costedRows,
    costedRevenue,
    orderCost,
    orderMargin,
    hasUnderOrder,
    agreedPriceOf,
    commitToDeal,
  };
}

export type ProductPickerState = ReturnType<typeof useProductPicker>;

/** Текст пустой таблицы каталога (не путать auth/error с «ещё грузится»). */
export function catalogEmptyMessage(
  status: ProductPickerState["catalogStatus"],
  hasSkus: boolean,
): string {
  if (hasSkus) return "Ничего не найдено — измените запрос или снимите фильтры";
  if (status === "loading") return "Загрузка номенклатуры…";
  if (status === "auth") {
    return "Нет доступа к номенклатуре — выйдите и войдите через Keycloak (нужен JWT).";
  }
  if (status === "error") return "Не удалось загрузить номенклатуру. Обновите страницу.";
  return "Номенклатура пуста.";
}

/**
 * Презентационная часть: строки корзины (qty/остаток/срок/маржа) + поиск/кандидаты +
 * итог/маржа заказа. БЕЗ CTA-кнопок (Добавить в сделку/Счёт/Повторить заказ) — их
 * компонует вызывающий, т.к. действие зависит от контекста (звонок по лиду создаёт
 * сделку; звонок/модалка по существующей сделке — добавляют позиции в неё).
 */
export function ProductPicker({
  state,
  fmt,
}: {
  state: ProductPickerState;
  fmt: (value: number) => string;
}) {
  const {
    rows,
    stock,
    query,
    setQuery,
    candidates,
    skus,
    catalogStatus,
    addSku,
    setRowQty,
    toggleRow,
    removeRow,
    agreedPriceOf,
  } = state;

  return (
    <div>
      {state.saveNotice && <p role="alert" className="mb-3 text-sm text-amber-700">{state.saveNotice}</p>}
      {rows.length > 0 && (
        <div className="mb-2 space-y-1.5">
          {rows.map((r, rowIndex) => {
            const st = stock[r.code];
            const price = agreedPriceOf(r);
            const s = srokOf(st);
            const m = price == null || st == null ? null : marginOf({ ...st, price });
            return (
              <div
                key={`${r.skuId}-${rowIndex}`}
                className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-2.5 py-1.5"
              >
                <input
                  type="checkbox"
                  checked={r.picked}
                  onChange={() => toggleRow(r)}
                  className="h-4 w-4 accent-money"
                  aria-label={`Включить ${r.title}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-semibold text-ink">{r.title}</div>
                  <div className="truncate text-[11px] text-faint">
                    {price == null ? "Цена не подтверждена · " : `${fmt(price)} · `}своб {st?.free ?? 0}
                    {st?.forecast ? ` · в пути ${st.forecast}` : ""} ·{" "}
                    <span className={s.cls}>{s.label}</span>
                    {m ? (
                      <span className="text-money"> · маржа {Math.round(m.pct)}%</span>
                    ) : st?.free === 0 ? (
                      <span className="text-faint"> · себес из предрасчёта</span>
                    ) : null}
                    {price != null ? (
                      <span className="ml-1 font-semibold text-ink">
                        · {fmt(price * r.qty)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <input
                  value={r.qty}
                  onChange={(e) =>
                    setRowQty(r, parseInt(e.target.value.replace(/\D/g, ""), 10) || 1)
                  }
                  inputMode="numeric"
                  className="w-12 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12.5px] tabular-nums text-ink outline-none focus:border-accent"
                  aria-label={`Количество ${r.title}`}
                />
                <button
                  type="button"
                  onClick={() => removeRow(r)}
                  aria-label="Убрать позицию"
                  className="text-faint hover:text-danger"
                >
                  <X size={14} />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Поиск/подбор из справочника */}
      <div className="flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5">
        <Search size={13} className="text-faint" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Подобрать товар по названию / коду…"
          className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none"
        />
      </div>
      {(query.trim() || rows.length === 0) && (
        <div className="mt-1 space-y-1">
          {candidates.map((s) => {
            const st = stock[s.code];
            const sk = srokOf(st);
            const m = marginOf(st);
            return (
              <button
                key={s.id}
                type="button"
                onClick={() => addSku(s)}
                className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-sunken"
              >
                <Plus size={13} className="mt-0.5 shrink-0 text-accent-ink" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink">
                      {s.title}
                    </span>
                    <span className="shrink-0 text-[11px] text-faint">{s.code}</span>
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] text-faint">
                    {st?.price ? `${fmt(st.price)} · ` : ""}своб {st?.free ?? 0}
                    {st?.forecast ? ` · в пути ${st.forecast}` : ""} ·{" "}
                    <span className={sk.cls}>{sk.label}</span>
                    {m ? (
                      <span className="text-money"> · маржа {Math.round(m.pct)}%</span>
                    ) : st?.free === 0 ? (
                      <span className="text-faint"> · предрасчёт</span>
                    ) : null}
                  </span>
                </span>
              </button>
            );
          })}
          {candidates.length === 0 && (
            <div className="px-2 py-1.5 text-[12px] text-faint">
              {catalogEmptyMessage(catalogStatus, skus.length > 0)}
            </div>
          )}
          {/* Провенанс данных (mdm-1c-data-provenance-ui): подчёркиваем, что остатки/цены —
              demo-зеркало 1С, а не боевые числа. */}
          <div className="px-2 pt-0.5 text-[11px] text-faint">
            номенклатура · 1С (MDM); цена — из реализаций периода; остатки склада — когда
            подключим регистр 1С
          </div>
        </div>
      )}
    </div>
  );
}

/** Итог + маржа заказа (общий футер под ProductPicker, используется звонком и модалкой).
 * `reserve` — намерение запросить резерв при выпуске счёта, ещё не факт резерва. */
export function ProductPickerTotals({
  state,
  fmt,
  reserve = false,
}: {
  state: ProductPickerState;
  fmt: (v: number) => string;
  reserve?: boolean;
}) {
  const { pickedRows, orderTotal, costedRows, costedRevenue, orderCost, orderMargin, hasUnderOrder } = state;
  if (!pickedRows.length) return null;
  return (
    <>
      {orderTotal > 0 && (
        <div className="flex items-center justify-between rounded-lg bg-sunken px-3 py-2 text-[12.5px]">
          <span className="text-muted">Итого{reserve ? " · резерв при выпуске" : ""}</span>
          <span className="font-bold text-ink">
            {fmt(orderTotal)}
            <span className="ml-1 font-normal text-faint">· с НДС {fmt(orderTotal * 1.2)}</span>
          </span>
        </div>
      )}
      {costedRows.length > 0 && costedRevenue > 0 && (
        <div className="flex items-center justify-between rounded-lg bg-money-soft px-3 py-2 text-[12px]">
          <span className="font-semibold text-money">
            Маржа{hasUnderOrder ? " · в наличии" : ""}
          </span>
          <span className="font-bold text-money">
            {fmt(orderMargin)} ({costedRevenue ? Math.round((orderMargin / costedRevenue) * 100) : 0}%)
            <span className="ml-1 font-normal text-faint">· себес {fmt(orderCost)}</span>
          </span>
        </div>
      )}
      {hasUnderOrder && (
        <p className="text-[11px] text-faint">
          Под-заказ позиции — себестоимость из предварительного расчёта (скоро); пока в марже не учтены.
        </p>
      )}
    </>
  );
}

/**
 * Полноэкранная модалка подбора товара для контекстов БЕЗ своего окна-кокпита
 * (сокращённая сделка — deal-drawer-preview.tsx). Окно звонка (call-window.tsx) уже
 * само модалка — там используется `ProductPicker`/`ProductPickerTotals` напрямую,
 * встроенными в свою колонку.
 */
export function ProductPickerModal({
  dealId,
  counterparty,
  onClose,
  onCommitted,
}: {
  dealId: string;
  counterparty: string;
  onClose: () => void;
  onCommitted?: () => void;
}) {
  const picker = useProductPicker(true, dealId);
  const { fmt } = useCurrency();
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [onOrder, setOnOrder] = useState(false);
  const invoiceRequestKey = useRef<string | null>(null);
  const action = useRef<object | null>(null);

  useEffect(() => {
    // Выбор относится только к открытой сделке.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOnOrder(false);
    invoiceRequestKey.current = null;
    action.current = null;
    setBusy(false);
  }, [dealId]);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 1900);
  }

  async function repeat() {
    setBusy(true);
    const n = await picker.repeatLastOrder(dealId);
    setBusy(false);
    flash(n ? `✅ Добавлено из прошлого заказа: ${n}` : "Прошлых заказов этого контрагента не найдено");
  }

  async function addToDeal() {
    if (action.current) return;
    if (!picker.pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    const operation = {};
    action.current = operation;
    const token = picker.contextToken();
    setBusy(true);
    try {
      const { ok, total } = await picker.commitToDeal(dealId, counterparty);
      if (!picker.isCurrentContext(token)) return;
      flash(ok === total ? `✅ Добавлено в сделку позиций: ${ok}/${total}` : `⚠️ Подтверждено позиций: ${ok}/${total}. Повторите перенос.`);
      if (ok === total) onCommitted?.();
    } catch {
      if (picker.isCurrentContext(token)) flash(UNCONFIRMED_ITEMS);
    } finally {
      if (action.current === operation) { action.current = null; setBusy(false); }
    }
  }

  async function issueInvoice() {
    if (action.current) return;
    if (!picker.pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    const operation = {};
    action.current = operation;
    // Вкладку печати открываем СИНХРОННО (до await) — иначе popup-блокировщик съест окно.
    const win = window.open("about:blank", "_blank");
    const token = picker.contextToken();
    let navigated = false;
    setBusy(true);
    const requestKey = onOrder ? (invoiceRequestKey.current ??= crypto.randomUUID()) : null;
    try {
      const saved = await picker.commitToDeal(dealId, counterparty);
      if (!picker.isCurrentContext(token)) return;
      if (saved.ok !== saved.total || !picker.canIssueInvoice(dealId)) {
        flash(`⚠️ Подтверждено позиций: ${saved.ok}/${saved.total}. Счёт не создан. Повторите перенос.`);
        return;
      }
      const { ok, message, renderUrl } = requestKey
        ? await issueDocument(dealId, "invoice", { reserve_mode: "on_order", request_key: requestKey })
        : await issueDocument(dealId, "invoice");
      if (ok && invoiceRequestKey.current === requestKey) invoiceRequestKey.current = null;
      if (!picker.isCurrentContext(token)) return;
      if (win && ok && renderUrl) { win.location.href = renderUrl; navigated = true; }
      flash(message);
      if (ok) {
        // Слайс 6 (A): успешный счёт ВСЕГДА назначает шаг «Проверить оплату» (+3 дн) — то же
        // правило, что в drawer-preview/CardMenu/call-window.tsx.
        void updateDeal(dealId, {
          next_step: INVOICE_NEXT_STEP,
          next_step_at: presetDateISO(3, Date.now()),
        });
        onCommitted?.();
      }
    } catch {
      if (picker.isCurrentContext(token)) flash("Результат оформления счёта не подтверждён. Проверьте документы сделки перед повтором.");
    } finally {
      // страховка от залипшего busy/окна-пустышки, если issue-путь когда-нибудь бросит
      if (!navigated) win?.close();
      if (action.current === operation) { action.current = null; setBusy(false); }
    }
  }

  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Подбор товара"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/45 p-4"
      onClick={() => { if (picker.canClose()) onClose(); }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[88vh] w-[640px] max-w-[96vw] flex-col overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div className="min-w-0 truncate text-[14px] font-bold text-ink">
            Подбор товара · {counterparty || "Контрагент не указан"}
          </div>
          <button
            type="button"
            onClick={() => { if (picker.canClose()) onClose(); }}
            aria-label="Закрыть"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken"
          >
            <X size={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-bold uppercase tracking-wide text-muted">
              Товар со склада
            </span>
            <button
              type="button"
              onClick={repeat}
              disabled={busy}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-accent-ink hover:text-accent"
            >
              <RefreshCw size={11} /> Повторить прошлый заказ
            </button>
          </div>
          <ProductPicker state={picker} fmt={fmt} />
          <ProductPickerTotals state={picker} fmt={fmt} />
          <label className="mt-2 flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={onOrder} disabled={busy}
              onChange={(e) => { setOnOrder(e.target.checked); invoiceRequestKey.current = null; }} />
            Под заказ — без резерва
          </label>
        </div>

        <footer className="grid grid-cols-2 gap-2 border-t border-line px-5 py-3.5">
          <Button
            variant="money"
            onClick={addToDeal}
            disabled={busy || !picker.pickedRows.length}
            icon={<ShoppingCart size={14} />}
          >
            Добавить в сделку
          </Button>
          <Button
            variant="secondary"
            onClick={issueInvoice}
            disabled={busy || !picker.pickedRows.length}
            icon={<Receipt size={14} />}
          >
            Выставить счёт
          </Button>
        </footer>

        {toast && (
          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-ink px-4 py-2 text-[12.5px] font-semibold text-canvas shadow-pop">
            {toast}
          </div>
        )}
      </div>
    </div>
  );
}
