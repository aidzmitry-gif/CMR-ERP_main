"use client";

import clsx from "clsx";
import { Plus, Receipt, RefreshCw, Search, ShoppingCart, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  addDealItem,
  createPriceQuote,
  fetchLastOrder,
  fetchSkus,
  fetchStock,
  issueDocument,
  type SkuOption,
} from "@/lib/api";
// Чистая доменная логика подбора (агрегация остатков/срок/маржа) живёт в src/lib/stock.ts
// с юнит-тестами (конвенция frontend/CLAUDE.md); здесь — только UI-обёртка.
import { aggregateStock, groupStockBySku, marginOf, srokOf, type SkuStock, type SkuWarehouseStock } from "@/lib/stock";
import { useCurrency } from "./currency-context";

/**
 * Подбор товара — общая логика/UI для окна звонка (call-window.tsx, встроенная колонка)
 * и модалки подбора из сокращённой сделки (deal-drawer-preview.tsx). Вынесено из
 * call-window.tsx, где раньше жило только там (см. память mockup-reuse-canonical-shell —
 * пикер по мотивам sales-deal-picker.html, упрощённый под уже рабочий стек без дерева категорий).
 */

export interface PickerRow {
  skuId: number;
  code: string;
  title: string;
  unit: string;
  qty: number;
  picked: boolean;
}

/**
 * Стейт подбора: справочник+остатки (грузятся при `active`), строки корзины, поиск,
 * повтор прошлого заказа, добавление в сделку. `active` — грузить данные только когда
 * пикер реально открыт (окно звонка/модалка), а не всегда в фоне.
 */
export function useProductPicker(active: boolean, refetchKey?: string) {
  const [skus, setSkus] = useState<SkuOption[]>([]);
  const [stock, setStock] = useState<Record<string, SkuStock>>({});
  // Per-warehouse разбивка (не агрегат) — форма «🏬 Подбор товара со склада»
  // (WarehousePickerModal): Остаток/Резерв/Свободно по каждому складу отдельно.
  const [warehouseStock, setWarehouseStock] = useState<Record<string, SkuWarehouseStock>>({});
  const [rows, setRows] = useState<PickerRow[]>([]);
  const [query, setQuery] = useState("");
  // rowsRef — свежий снимок корзины для repeatLastOrder (дедуп по актуальным строкам);
  // genRef — «поколение» контекста: reset() его двигает, поздний async сверяет и не всыпает
  // позиции чужого контрагента, если окно звонка успело переключиться на другую сделку.
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const genRef = useRef(0);

  // refetchKey (id открытой сделки/лида) в deps: остатки/цены перезагружаются и при прямой
  // смене контекста звонка (сделка→сделка без промежуточного закрытия), а не только по active.
  useEffect(() => {
    if (!active) return;
    let alive = true;
    void fetchSkus().then((list) => {
      if (alive) setSkus(list);
    });
    void fetchStock().then((rows) => {
      if (alive) {
        setStock(aggregateStock(rows));
        setWarehouseStock(groupStockBySku(rows));
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
      { skuId: s.id, code: s.code, title: s.title, unit: s.unit, qty: 1, picked: true },
    ]);
    setQuery("");
  }
  /** Добавить с явным кол-вом (WarehousePickerModal — подбор со склада на заданный остаток);
   *  повторный подбор уже добавленной позиции суммирует количество, не дублирует строку. */
  function addSkuWithQty(s: SkuOption, qty: number) {
    setRows((r) => {
      const existing = r.find((x) => x.skuId === s.id);
      if (existing) {
        return r.map((x) => (x.skuId === s.id ? { ...x, qty: x.qty + qty, picked: true } : x));
      }
      return [...r, { skuId: s.id, code: s.code, title: s.title, unit: s.unit, qty, picked: true }];
    });
  }
  function setRowQty(skuId: number, qty: number) {
    setRows((r) => r.map((x) => (x.skuId === skuId ? { ...x, qty: Math.max(1, qty) } : x)));
  }
  function toggleRow(skuId: number) {
    setRows((r) => r.map((x) => (x.skuId === skuId ? { ...x, picked: !x.picked } : x)));
  }
  function removeRow(skuId: number) {
    setRows((r) => r.filter((x) => x.skuId !== skuId));
  }
  function reset() {
    genRef.current++;
    setRows([]);
    setQuery("");
  }

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
          skuId: it.sku_id,
          code: it.code,
          title: it.title,
          unit: it.unit,
          qty: Math.max(1, Math.round(it.qty)),
          picked: true,
        })),
      ]);
    }
    return added.length;
  }

  const pickedRows = rows.filter((r) => r.picked);
  // Итог заказа по ценам со склада (для счёта).
  const orderTotal = pickedRows.reduce((sum, r) => sum + (stock[r.code]?.price ?? 0) * r.qty, 0);
  // Себес/маржа — ТОЛЬКО по позициям «в наличии» (себес из 1С); под-заказ — предрасчёт (позже).
  const costedRows = pickedRows.filter((r) => stock[r.code]?.cost != null);
  const costedRevenue = costedRows.reduce((s, r) => s + (stock[r.code]?.price ?? 0) * r.qty, 0);
  const orderCost = costedRows.reduce((s, r) => s + (stock[r.code]?.cost ?? 0) * r.qty, 0);
  const orderMargin = costedRevenue - orderCost;
  const hasUnderOrder = pickedRows.some((r) => stock[r.code]?.cost == null);

  /** Добавить отмеченные позиции в РЕАЛЬНУЮ сделку + зафиксировать цену со склада клиенту.
   * Позиции и котировки независимы между собой — шлём параллельно; котировки ДОЖИДАЕМСЯ
   * (await, не fire-and-forget), иначе следом за commitToDeal рендер счёта прочитает ещё
   * не записанные PriceQuote и напечатает цены 0.00. */
  async function commitToDeal(dealId: string, counterparty: string): Promise<{ ok: number; total: number }> {
    const results = await Promise.all(pickedRows.map((r) => addDealItem(dealId, r.skuId, r.qty)));
    await Promise.all(
      pickedRows.map((r) => {
        const p = stock[r.code]?.price;
        return p ? createPriceQuote(r.code, counterparty, p) : Promise.resolve(true);
      }),
    );
    return { ok: results.filter(Boolean).length, total: pickedRows.length };
  }

  return {
    skus,
    stock,
    warehouseStock,
    rows,
    query,
    setQuery,
    candidates,
    addSku,
    addSkuWithQty,
    setRowQty,
    toggleRow,
    removeRow,
    reset,
    repeatLastOrder,
    pickedRows,
    orderTotal,
    costedRows,
    costedRevenue,
    orderCost,
    orderMargin,
    hasUnderOrder,
    commitToDeal,
  };
}

export type ProductPickerState = ReturnType<typeof useProductPicker>;

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
  const { rows, stock, query, setQuery, candidates, skus, addSku, setRowQty, toggleRow, removeRow } = state;

  return (
    <div>
      {rows.length > 0 && (
        <div className="mb-2 space-y-1.5">
          {rows.map((r) => {
            const st = stock[r.code];
            const s = srokOf(st);
            const m = marginOf(st);
            return (
              <div
                key={r.skuId}
                className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-2.5 py-1.5"
              >
                <input
                  type="checkbox"
                  checked={r.picked}
                  onChange={() => toggleRow(r.skuId)}
                  className="h-4 w-4 accent-money"
                  aria-label={`Включить ${r.title}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-semibold text-ink">{r.title}</div>
                  <div className="truncate text-[11px] text-faint">
                    {st?.price ? `${fmt(st.price)} · ` : ""}своб {st?.free ?? 0}
                    {st?.forecast ? ` · в пути ${st.forecast}` : ""} ·{" "}
                    <span className={s.cls}>{s.label}</span>
                    {m ? (
                      <span className="text-money"> · маржа {Math.round(m.pct)}%</span>
                    ) : st?.free === 0 ? (
                      <span className="text-faint"> · себес из предрасчёта</span>
                    ) : null}
                    {st?.price ? (
                      <span className="ml-1 font-semibold text-ink">
                        · {fmt(st.price * r.qty)}
                      </span>
                    ) : null}
                  </div>
                </div>
                <input
                  value={r.qty}
                  onChange={(e) =>
                    setRowQty(r.skuId, parseInt(e.target.value.replace(/\D/g, ""), 10) || 1)
                  }
                  inputMode="numeric"
                  className="w-12 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12.5px] tabular-nums text-ink outline-none focus:border-accent"
                  aria-label={`Количество ${r.title}`}
                />
                <button
                  type="button"
                  onClick={() => removeRow(r.skuId)}
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
              {skus.length ? "Ничего не найдено" : "Загрузка номенклатуры…"}
            </div>
          )}
          {/* Провенанс данных (mdm-1c-data-provenance-ui): подчёркиваем, что остатки/цены —
              demo-зеркало 1С, а не боевые числа. */}
          <div className="px-2 pt-0.5 text-[11px] text-faint">
            номенклатура · 1С (через MDM); остатки по складам, цена и срок — из 1С (demo); резерв
            под счёт — SALES-51
          </div>
        </div>
      )}
    </div>
  );
}

/** Итог + маржа заказа (общий футер под ProductPicker, используется звонком и модалкой).
 * `reserve` — помечает итог как резервируемый (чекбокс «Зарезервировать под счёт» живёт
 * в окне звонка; в модалке подбора его нет — по умолчанию не показываем). */
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
          <span className="text-muted">Итого{reserve ? " · резерв" : ""}</span>
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
    if (!picker.pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    setBusy(true);
    const { ok, total } = await picker.commitToDeal(dealId, counterparty);
    setBusy(false);
    flash(`✅ Добавлено в сделку позиций: ${ok}/${total}`);
    onCommitted?.();
  }

  async function issueInvoice() {
    if (!picker.pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    // Вкладку печати открываем СИНХРОННО (до await) — иначе popup-блокировщик съест окно.
    const win = window.open("about:blank", "_blank");
    setBusy(true);
    await picker.commitToDeal(dealId, counterparty); // позиции+котировки записаны ДО рендера
    const { ok, message, renderUrl } = await issueDocument(dealId, "invoice");
    setBusy(false);
    if (win && ok && renderUrl) win.location.href = renderUrl;
    else win?.close();
    flash(message);
    if (ok) onCommitted?.();
  }

  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Подбор товара"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/45 p-4"
      onClick={onClose}
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
            onClick={onClose}
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

/**
 * «🏬 Подбор товара со склада» — модалка per-warehouse разбивки (порт sales-call-popup.html,
 * stockMoreOv): Остаток/Резерв/Свободно по КАЖДОМУ складу отдельно (не суммой, как в основном
 * ProductPicker) — менеджер видит, с какого склада реально есть товар, прежде чем обещать
 * клиенту. Количество — одно на SKU (не по складам): заказ/addDealItem не различают склад
 * отгрузки, разбивка тут только помогает решить, сколько реально можно продать.
 */
export function WarehousePickerModal({
  state,
  fmt,
  onClose,
}: {
  state: ProductPickerState;
  fmt: (value: number) => string;
  onClose: () => void;
}) {
  const { skus, warehouseStock, addSkuWithQty } = state;
  const [search, setSearch] = useState("");
  const [warehouse, setWarehouse] = useState("Все склады");
  const [qtyBySku, setQtyBySku] = useState<Record<number, number>>({});
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const allWarehouses = useMemo(() => {
    const set = new Set<string>();
    Object.values(warehouseStock).forEach((s) => s.rows.forEach((r) => set.add(r.warehouse)));
    return Array.from(set).sort();
  }, [warehouseStock]);

  const q = search.trim().toLowerCase();
  // Без остатков (по выбранному складу) не показываем — это форма «подбор со склада»,
  // общий безостаточный поиск уже есть в ProductPicker.
  const items = skus
    .filter((s) => !q || `${s.title} ${s.code}`.toLowerCase().includes(q))
    .map((s) => {
      const st = warehouseStock[s.code];
      const rows = (st?.rows ?? []).filter((r) => warehouse === "Все склады" || r.warehouse === warehouse);
      return { sku: s, stock: st, rows };
    })
    .filter((it) => it.rows.length > 0);

  function toggle(skuId: number) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(skuId)) {
        next.delete(skuId);
      } else {
        next.add(skuId);
        setQtyBySku((prevQty) => (prevQty[skuId] ? prevQty : { ...prevQty, [skuId]: 1 }));
      }
      return next;
    });
  }

  function setQty(skuId: number, qty: number) {
    setQtyBySku((prev) => ({ ...prev, [skuId]: Math.max(0, qty) }));
    if (qty > 0) setChecked((prev) => new Set(prev).add(skuId));
  }

  function confirm() {
    items.forEach(({ sku }) => {
      if (checked.has(sku.id)) addSkuWithQty(sku, qtyBySku[sku.id] || 1);
    });
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Подбор товара со склада"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/45 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[88vh] w-[820px] max-w-[96vw] flex-col overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        <header className="flex items-center justify-between gap-2 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <div className="truncate text-[14px] font-bold text-ink">🏬 Подбор товара со склада</div>
            <div className="text-[11px] font-medium text-faint">
              остаток · резерв · свободно по каждому складу
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex items-center gap-2 border-b border-line px-5 py-3">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по номенклатуре…"
              className="w-full rounded-lg border border-line bg-surface py-1.5 pl-8 pr-3 text-[12.5px] text-ink outline-none focus:border-accent"
            />
          </div>
          <select
            value={warehouse}
            onChange={(e) => setWarehouse(e.target.value)}
            aria-label="Склад"
            className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-ink outline-none"
          >
            <option>Все склады</option>
            {allWarehouses.map((w) => (
              <option key={w}>{w}</option>
            ))}
          </select>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          <table className="w-full text-[12px]">
            <thead className="border-b border-line text-left text-[11px] text-muted">
              <tr>
                <th className="w-8 py-1.5" />
                <th className="py-1.5 font-medium">Товар</th>
                <th className="py-1.5 font-medium">Склад</th>
                <th className="py-1.5 text-right font-medium">Остаток</th>
                <th className="py-1.5 text-right font-medium">Резерв</th>
                <th className="py-1.5 text-right font-medium">Свободно</th>
                <th className="py-1.5 text-right font-medium">Цена</th>
                <th className="py-1.5 text-right font-medium">Кол-во</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-faint">
                    {skus.length ? "Ничего не найдено на этом складе" : "Загрузка номенклатуры…"}
                  </td>
                </tr>
              )}
              {items.map(({ sku, stock, rows }) => {
                const totFree = rows.reduce((s, r) => s + r.free, 0);
                return rows.map((r, i) => (
                  <tr key={`${sku.id}-${r.warehouse}`} className="border-b border-line last:border-0">
                    {i === 0 && (
                      <>
                        <td rowSpan={rows.length} className="align-top py-2">
                          <input
                            type="checkbox"
                            checked={checked.has(sku.id)}
                            onChange={() => toggle(sku.id)}
                            className="h-4 w-4 accent-money"
                            aria-label={`Выбрать ${sku.title}`}
                          />
                        </td>
                        <td rowSpan={rows.length} className="align-top py-2 pr-2">
                          <div className="font-semibold text-ink">{sku.title}</div>
                          <div className="text-[11px] text-faint">
                            {sku.code} · Σ свободно {totFree} ·{" "}
                            {rows.length > 1 ? `${rows.length} склада` : "1 склад"}
                          </div>
                        </td>
                      </>
                    )}
                    <td className="py-2 text-muted">🏬 {r.warehouse}</td>
                    <td className="py-2 text-right tabular-nums text-ink">{r.on}</td>
                    <td className="py-2 text-right tabular-nums text-amber-600">{r.reserved || "—"}</td>
                    <td
                      className={clsx(
                        "py-2 text-right tabular-nums font-semibold",
                        r.free > 0 && r.free <= 3 ? "text-amber-600" : "text-money",
                      )}
                    >
                      {r.free}
                      {r.free > 0 && r.free <= 3 ? " ⚠" : ""}
                    </td>
                    {i === 0 && (
                      <td rowSpan={rows.length} className="align-top py-2 text-right tabular-nums text-ink">
                        {stock?.price ? fmt(stock.price) : "—"}
                      </td>
                    )}
                    {i === 0 && (
                      <td rowSpan={rows.length} className="align-top py-2 text-right">
                        <input
                          value={qtyBySku[sku.id] ?? (checked.has(sku.id) ? 1 : 0)}
                          onChange={(e) =>
                            setQty(sku.id, parseInt(e.target.value.replace(/\D/g, ""), 10) || 0)
                          }
                          inputMode="numeric"
                          className="w-14 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12px] tabular-nums text-ink outline-none focus:border-accent"
                          aria-label={`Количество ${sku.title}`}
                        />
                      </td>
                    )}
                  </tr>
                ));
              })}
            </tbody>
          </table>
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-muted">
            <span>
              <b className="text-ink">Остаток</b> — всего на складе
            </span>
            <span>
              · <b className="text-amber-600">Резерв</b> — под другие заказы
            </span>
            <span>
              · <b className="text-money">Свободно</b> — доступно к продаже (ATP)
            </span>
          </div>
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-line px-5 py-3.5">
          <span className="text-[12px] text-muted">
            Выбрано: {checked.size} {checked.size === 1 ? "позиция" : "позиций"}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button
              variant="money"
              onClick={confirm}
              disabled={checked.size === 0}
              icon={<Plus size={14} />}
            >
              Добавить в заказ
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
