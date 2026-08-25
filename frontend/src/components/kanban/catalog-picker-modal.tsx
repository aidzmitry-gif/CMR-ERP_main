"use client";

import clsx from "clsx";
import { RefreshCw, Search, ShoppingCart, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { requestApproval, type SkuOption } from "@/lib/api";
import { marginOf, srokOf, type SkuStock, type SkuWarehouseStock } from "@/lib/stock";
import { useCurrency } from "./currency-context";
import { catalogEmptyMessage, type ProductPickerState } from "./product-picker";

/**
 * Компактная модалка подбора товара (порт sales-catalog-picker-compact.html —
 * 1С/Битрикс-стиль: дерево разделов + плотная таблица + попап «Ввод количества и цены»).
 * Данные/логика — общий `useProductPicker` (product-picker.tsx), тут только другая
 * презентация поверх того же стейта (не дублирует fetch/агрегацию остатков/маржу).
 *
 * ПОРОГ МАРЖИ («Макс. скидка N%», аналог 1С): в кодовой базе нет общей константы
 * AIOS_MIN_MARGIN на фронте (проверено — grep по MIN_MARGIN/FLOOR пуст), поэтому
 * заводим именованную локальную константу с явным полом.
 */
const MIN_MARGIN_FLOOR_PCT = 12; // нет общего порога маржи на фронте — если появится, взять из него

/**
 * Разделы/Параметры (Напряжение/Ёмкость) из мокапа требуют категории и атрибутов SKU —
 * `SkuOption` (src/lib/api.ts) даёт только { id, code, title, unit }, БЕЗ группы/категории
 * и БЕЗ структурных атрибутов. Дерево и фасеты поэтому не рендерим (честный пропуск, не
 * выдумываем). Раздел «Все товары» в левой панели — единственная честная замена дерева.
 * TODO(backend): SKU category/group + attributes (voltage/capacity) not in API — добавить
 * поле в SkuOption (напр. group: string | null, attrs: Record<string,string> | null), тогда
 * здесь включить дерево «Разделы» и фасеты «Параметры».
 */

interface RowVm {
  sku: SkuOption;
  st?: SkuStock;
}

export function CatalogPickerModal({
  dealId,
  counterparty = "",
  onClose,
  onCommitted,
  state,
}: {
  /** Реальная сделка — есть у deal-drawer и у звонка по СУЩЕСТВУЮЩЕЙ сделке. Для звонка по
   *  лиду/новому клиенту (сделки ещё нет) — не передаётся: «Перенести в документ» тогда не
   *  коммитит на бэк, а просто закрывает модалку (позиции остаются в общем `state.rows` —
   *  их подхватит commitOrder/createDeal вызывающей стороны, как раньше делал
   *  WarehousePickerModal). */
  dealId?: string;
  counterparty?: string;
  onClose: () => void;
  onCommitted?: () => void;
  /** Общий стейт подбора — переиспользуем из вызывающей стороны (окно звонка уже держит
   *  свой `useProductPicker`; drawer создаёт новый). Не дублируем fetch внутри модалки. */
  state: ProductPickerState;
}) {
  const picker = state;
  const { skus, catalogStatus, stock, warehouseStock, rows, addSkuWithQty, setRowPrice, removeRow } =
    picker;
  const { fmt } = useCurrency();

  const [query, setQuery] = useState("");
  const [exact, setExact] = useState(false);
  const [inStockOnly, setInStockOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [kbdIndex, setKbdIndex] = useState(-1);
  const [popoverSku, setPopoverSku] = useState<SkuOption | null>(null);
  // «Мягкий» гардрейл маржи: скидка ниже порога не блокирует перенос, но требует ОДНОГО
  // подтверждения — по нему уходит запрос на согласование скидки (kind=deal.discount, тот
  // же контракт, что и DealApprovals на полной карточке сделки).
  const [confirmingDiscount, setConfirmingDiscount] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const blendedMarginPct =
    picker.costedRows.length > 0 && picker.costedRevenue > 0
      ? (picker.orderMargin / picker.costedRevenue) * 100
      : null;
  const belowFloor = blendedMarginPct != null && blendedMarginPct < MIN_MARGIN_FLOOR_PCT;
  const transferLabel = confirmingDiscount
    ? "Да, перенести (на согласование)"
    : belowFloor
      ? "🔒 Перенести → согласовать скидку"
      : "Перенести в документ";

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(null), 1900);
  }

  const q = query.trim().toLowerCase();
  const rowBySkuId = new Map(rows.map((r) => [r.skuId, r]));

  const filtered: RowVm[] = useMemo(() => {
    return skus
      .map((sku) => ({ sku, st: stock[sku.code] }))
      .filter(({ sku }) => {
        if (!q) return true;
        const hay = exact ? `${sku.title} ${sku.code}`.toLowerCase() : `${sku.title} ${sku.code}`.toLowerCase();
        if (exact) return hay.includes(q);
        return q.split(/\s+/).every((w) => w.length < 2 || hay.includes(w));
      })
      .filter(({ st }) => !inStockOnly || (st?.free ?? 0) > 0);
  }, [skus, stock, q, exact, inStockOnly]);

  // группировка — без category в SKU группировать некуда, единая секция «Все товары»
  const groupLabel = "Все товары";

  function highlight(title: string): React.ReactNode {
    if (!q) return title;
    const low = title.toLowerCase();
    for (const w of q.split(/\s+/)) {
      if (w.length < 2) continue;
      const i = low.indexOf(w);
      if (i >= 0) {
        return (
          <>
            {title.slice(0, i)}
            <mark className="rounded bg-accent/20 px-px text-accent-ink">{title.slice(i, i + w.length)}</mark>
            {title.slice(i + w.length)}
          </>
        );
      }
    }
    return title;
  }

  async function repeat() {
    if (!dealId) return flash("Повтор заказа доступен только для существующей сделки");
    setBusy(true);
    const n = await picker.repeatLastOrder(dealId);
    setBusy(false);
    flash(n ? `✅ Добавлено из прошлого заказа: ${n}` : "Прошлых заказов этого контрагента не найдено");
  }

  /** «Перенести в документ»: у РЕАЛЬНОЙ сделки — коммитим позиции на бэк сразу (как
   *  ProductPickerModal). Без dealId (звонок по лиду/новому клиенту — сделки ещё нет) —
   *  просто закрываем модалку, позиции остаются в общем state.rows и уходят в бэк позже
   *  через commitOrder/createDeal вызывающей стороны (тот же контракт, что и у
   *  WarehousePickerModal раньше).
   *
   *  Маржа ниже порога (belowFloor) — НЕ блокирует перенос: первый клик показывает inline-
   *  подтверждение (banner ниже), второй — коммитит как обычно И параллельно уходит запрос
   *  на согласование скидки (requestApproval, kind=deal.discount) — тот же путь, что и
   *  DealApprovals на полной карточке. Жёсткий блок «не пускать в 1С» — не делаем: см. ROP-
   *  решение в памяти сессии (мягкий гейт, не хард-блок). */
  async function transfer() {
    if (!picker.pickedRows.length) return flash("Отметьте хотя бы одну позицию");
    if (belowFloor && !confirmingDiscount) {
      setConfirmingDiscount(true);
      return;
    }
    if (!dealId) {
      onClose();
      return;
    }
    setBusy(true);
    const tasks: Promise<unknown>[] = [picker.commitToDeal(dealId, counterparty)];
    if (belowFloor) tasks.push(requestApproval(dealId, "deal.discount"));
    const [committed] = await Promise.all(tasks);
    const { ok, total } = committed as { ok: number; total: number };
    setBusy(false);
    setConfirmingDiscount(false);
    flash(
      belowFloor
        ? `✅ Перенесено: ${ok}/${total} · скидка отправлена на согласование РОПу`
        : `✅ Перенесено в документ позиций: ${ok}/${total}`,
    );
    onCommitted?.();
  }

  // Корзину поправили после того, как показали подтверждение согласования скидки — сбрасываем,
  // чтобы «Да, перенести» не сработало вслепую против уже другой (пересчитанной) маржи.
  useEffect(() => {
    setConfirmingDiscount(false);
  }, [rows]);

  function onSearchKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!filtered.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setKbdIndex((i) => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setKbdIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      if (kbdIndex >= 0 && filtered[kbdIndex]) {
        e.preventDefault();
        setPopoverSku(filtered[kbdIndex].sku);
      }
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        if (popoverSku) setPopoverSku(null);
        else onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [popoverSku]);

  // Автофокус на поиск при открытии — клавиатура ↑↓/Enter работает сразу без лишнего клика.
  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  const pickedCount = picker.pickedRows.length;

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
        className="flex h-[86vh] max-h-[660px] w-[1180px] max-w-[96vw] flex-col overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        {/* header */}
        <header className="flex items-center gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-[14px] font-bold text-ink">
              🛒 Подбор товара · {counterparty || "Контрагент не указан"}
            </div>
            <div className="text-[11px] text-faint">открывается поверх сделки — без перехода на другой экран</div>
          </div>
          <div className="flex-1" />
          <Button variant="primary" size="sm" onClick={transfer} disabled={busy || !pickedCount} icon={<ShoppingCart size={13} />}>
            {transferLabel}
          </Button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-sunken"
          >
            <X size={16} />
          </button>
        </header>

        {/* toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2">
          <div className="relative min-w-[220px] flex-1">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setKbdIndex(-1);
              }}
              onKeyDown={onSearchKey}
              placeholder="Название / артикул — напр. «6СТ-190»"
              autoComplete="off"
              className="w-full rounded-lg border border-line bg-surface py-1.5 pl-7 pr-3 text-[13px] text-ink outline-none focus:border-accent"
            />
          </div>
          <label className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-muted">
            <input
              type="checkbox"
              checked={exact}
              onChange={(e) => setExact(e.target.checked)}
              className="h-[15px] w-[15px] accent-accent"
            />
            по точному соответствию
          </label>
          <label className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] text-muted">
            <input
              type="checkbox"
              checked={inStockOnly}
              onChange={(e) => setInStockOnly(e.target.checked)}
              className="h-[15px] w-[15px] accent-accent"
            />
            только в наличии
          </label>
          <button
            type="button"
            onClick={repeat}
            disabled={busy}
            className="whitespace-nowrap rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12px] font-semibold text-accent-ink hover:bg-accent/10"
          >
            <RefreshCw size={11} className="mr-1 inline" /> Прошлый заказ
          </button>
          {/* «🧰 Комплект ТО» — нет данных о комплектах в API, честно не рендерим (не выдумываем) */}
          <span className="ml-auto whitespace-nowrap text-[11px] text-faint">↑↓ · Enter — подобрать</span>
        </div>

        {/* body: left tree (honest-empty) + right table */}
        <div className="flex min-h-0 flex-1">
          <aside className="w-[190px] shrink-0 overflow-auto border-r border-line bg-surface p-2">
            <div className="px-2 pb-1.5 pt-1 text-[10.5px] font-bold uppercase tracking-wide text-faint">Разделы</div>
            <div className="flex items-center gap-1.5 rounded-lg bg-accent/10 px-2 py-1.5 text-[12.5px] font-semibold text-accent-ink">
              {groupLabel}
              <span className="ml-auto rounded bg-surface px-1.5 text-[10.5px] font-semibold text-faint">
                {skus.length}
              </span>
            </div>
            <p className="mt-3 px-2 text-[10.5px] leading-snug text-faint">
              Дерево категорий и параметры (Напряжение/Ёмкость) появятся, когда номенклатура
              будет отдавать группу/атрибуты — сейчас в API их нет.
            </p>
          </aside>

          <div className="min-w-0 flex-1 overflow-auto">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 z-[1] bg-sunken text-left text-[10px] font-bold uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-2.5 py-2">Наименование</th>
                  <th className="px-2 py-2">Артикул</th>
                  <th className="px-2 py-2 text-right">Цена</th>
                  <th className="px-2 py-2 text-right">Своб.</th>
                  <th className="px-2 py-2">Доступно</th>
                  <th className="px-2 py-2 text-center">Маржа</th>
                  <th className="px-2 py-2 text-center">Кол-во</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-9 text-center text-faint">
                      {catalogEmptyMessage(catalogStatus, skus.length > 0)}
                      {catalogStatus === "auth" && (
                        <div className="mt-3">
                          <a href="/login" className="text-accent-ink underline">
                            Войти через Keycloak
                          </a>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
                {filtered.length > 0 && (
                  <>
                    <tr>
                      <td colSpan={7} className="px-2.5 pb-0.5 pt-2 text-[10.5px] font-bold uppercase tracking-wide text-faint">
                        {groupLabel}
                      </td>
                    </tr>
                    {filtered.map(({ sku, st }, i) => {
                      const row = rowBySkuId.get(sku.id);
                      const sk = srokOf(st);
                      // Цена клиенту: отредактированная в попапе — приоритетнее цены со склада;
                      // маржа считается ОТ НЕЁ ЖЕ (иначе бейдж соврёт зелёным при уже данной скидке).
                      const effPrice = row?.priceOverride ?? st?.price;
                      const m = st ? marginOf({ ...st, price: effPrice ?? st.price }) : null;
                      const low = (st?.free ?? 0) > 0 && (st?.free ?? 0) <= 5;
                      return (
                        <tr
                          key={sku.id}
                          data-row
                          onClick={() => setPopoverSku(sku)}
                          className={clsx(
                            "cursor-pointer border-b border-line last:border-0 hover:bg-sunken",
                            row && "bg-money-soft",
                            kbdIndex === i && "bg-accent/10",
                          )}
                        >
                          <td className="px-2.5 py-1.5 font-semibold text-ink">{highlight(sku.title)}</td>
                          <td className="px-2 py-1.5 whitespace-nowrap text-[11px] text-muted">{sku.code}</td>
                          <td className="px-2 py-1.5 text-right font-bold text-ink">
                            {effPrice ? fmt(effPrice) : "—"}
                            {row?.priceOverride != null && (
                              <span className="ml-1 text-[10px] font-semibold text-accent-ink" title="Цена отредактирована вручную">
                                ✎
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-right">
                            <span className={clsx("font-bold", low ? "text-danger" : "text-money")}>
                              {st?.free ?? 0}
                              {low ? " ⚠" : ""}
                            </span>
                          </td>
                          <td className="px-2 py-1.5 whitespace-nowrap text-muted">
                            <span className={sk.cls}>{sk.label}</span>
                            {st?.forecast ? <span className="ml-1 font-semibold text-amber-600">🚚+{st.forecast}</span> : null}
                          </td>
                          <td className="px-2 py-1.5 text-center">
                            {m ? (
                              <span
                                className={clsx(
                                  "rounded px-1.5 py-0.5 text-[11px] font-bold",
                                  m.pct >= 25
                                    ? "bg-money-soft text-money"
                                    : m.pct >= MIN_MARGIN_FLOOR_PCT
                                      ? "bg-amber-50 text-amber-600 dark:bg-amber-500/10"
                                      : "bg-red-50 text-danger dark:bg-red-500/10",
                                )}
                              >
                                GP {Math.round(m.pct)}%
                              </span>
                            ) : (
                              <span className="rounded bg-sunken px-1.5 py-0.5 text-[11px] font-semibold text-faint">
                                маржа —
                              </span>
                            )}
                          </td>
                          <td className="px-2 py-1.5 text-center" onClick={(e) => e.stopPropagation()}>
                            {row ? (
                              <div className="inline-flex items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => (row.qty > 1 ? picker.setRowQty(sku.id, row.qty - 1) : removeRow(sku.id))}
                                  className="flex h-6 w-6 items-center justify-center rounded-md border border-line bg-surface text-ink hover:bg-sunken"
                                >
                                  −
                                </button>
                                <span
                                  onClick={() => setPopoverSku(sku)}
                                  className="min-w-[28px] cursor-pointer text-center font-bold tabular-nums text-ink underline decoration-dotted underline-offset-2"
                                >
                                  {row.qty}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => picker.setRowQty(sku.id, row.qty + 1)}
                                  className="flex h-6 w-6 items-center justify-center rounded-md border border-line bg-surface text-ink hover:bg-sunken"
                                >
                                  +
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setPopoverSku(sku)}
                                className="whitespace-nowrap rounded-md bg-accent px-2 py-1 text-[11.5px] font-bold text-white hover:bg-accent-ink"
                              >
                                Подобрать
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </>
                )}
              </tbody>
            </table>
          </div>

          {/* Корзина — что подобрано; тут же правим (кол-во / убрать / исключить из счёта) без ухода из окна */}
          <aside className="flex w-[272px] shrink-0 flex-col border-l border-line bg-surface">
            <div className="flex items-center gap-2 border-b border-line px-3 py-2">
              <ShoppingCart size={13} className="text-muted" />
              <span className="text-[11px] font-bold uppercase tracking-wide text-faint">Корзина</span>
              <span className="ml-auto rounded bg-sunken px-1.5 text-[11px] font-bold text-muted">{rows.length}</span>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {rows.length === 0 ? (
                <p className="px-3 py-8 text-center text-[11.5px] leading-snug text-faint">
                  Пусто. Добавляйте товар из таблицы — он появится здесь, и его можно поправить до переноса в счёт.
                </p>
              ) : (
                rows.map((r) => {
                  const price = r.priceOverride ?? stock[r.code]?.price ?? 0;
                  return (
                    <div key={r.skuId} className={clsx("border-b border-line px-3 py-2", !r.picked && "opacity-45")}>
                      <div className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          checked={r.picked}
                          onChange={() => picker.toggleRow(r.skuId)}
                          aria-label="Включить в счёт"
                          title="Включить/исключить из счёта (не удаляя)"
                          className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-accent"
                        />
                        <div className="min-w-0 flex-1 text-[12px] font-semibold leading-tight text-ink">{r.title}</div>
                        <button
                          type="button"
                          onClick={() => picker.removeRow(r.skuId)}
                          aria-label="Убрать из корзины"
                          className="shrink-0 text-faint hover:text-danger"
                        >
                          <X size={13} />
                        </button>
                      </div>
                      <div className="mt-1.5 flex items-center gap-1.5 pl-6">
                        <button
                          type="button"
                          onClick={() => (r.qty > 1 ? picker.setRowQty(r.skuId, r.qty - 1) : picker.removeRow(r.skuId))}
                          className="flex h-5 w-5 items-center justify-center rounded border border-line bg-surface text-ink hover:bg-sunken"
                        >
                          −
                        </button>
                        <span className="min-w-[24px] text-center text-[12px] font-bold tabular-nums text-ink">{r.qty}</span>
                        <button
                          type="button"
                          onClick={() => picker.setRowQty(r.skuId, r.qty + 1)}
                          className="flex h-5 w-5 items-center justify-center rounded border border-line bg-surface text-ink hover:bg-sunken"
                        >
                          +
                        </button>
                        <button
                          type="button"
                          onClick={() => setPopoverSku({ id: r.skuId, code: r.code, title: r.title, unit: r.unit })}
                          title="Изменить количество/цену"
                          className="text-[10.5px] text-faint underline decoration-dotted underline-offset-2 hover:text-accent-ink"
                        >
                          × {price ? fmt(price) : "—"}
                          {r.priceOverride != null ? " ✎" : ""}
                        </button>
                        <span className="ml-auto text-[12px] font-bold text-ink">{price ? fmt(price * r.qty) : "—"}</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
            <div className="border-t border-line px-3 py-2 text-[12px]">
              <div className="flex items-center justify-between">
                <span className="text-muted">Итого{pickedCount < rows.length ? ` (${pickedCount} в счёт)` : ""}</span>
                <b className="text-ink">{fmt(picker.orderTotal)}</b>
              </div>
              {picker.costedRows.length > 0 && picker.costedRevenue > 0 && (
                <div className="mt-0.5 flex items-center justify-between">
                  <span className="text-muted">Маржа</span>
                  <b className={picker.orderMargin >= 0 ? "text-money" : "text-danger"}>
                    {fmt(picker.orderMargin)} ({Math.round((picker.orderMargin / picker.costedRevenue) * 100)}%)
                  </b>
                </div>
              )}
            </div>
          </aside>
        </div>

        {/* footer */}
        <footer className="flex flex-col gap-2 border-t border-line px-4 py-2.5">
          {confirmingDiscount && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-[12px] font-semibold text-danger dark:bg-red-500/10">
              ⚠ Маржа {Math.round(blendedMarginPct ?? 0)}% ниже порога {MIN_MARGIN_FLOOR_PCT}% — перенос уйдёт в счёт СЕЙЧАС,
              а скидка отдельно уйдёт на согласование РОПу (не блокирует, но требует подтверждения).
            </div>
          )}
          <div className="flex items-center gap-3">
            <div className="text-[12.5px] text-muted">
              Подобрано: <b className="text-ink">{pickedCount}</b>
              {pickedCount > 0 && (
                <>
                  {" "}
                  · сумма <b className="text-ink">{fmt(picker.orderTotal)}</b>
                  {picker.costedRows.length > 0 && picker.costedRevenue > 0 && (
                    <>
                      {" "}
                      · маржа{" "}
                      <b className={belowFloor ? "text-danger" : "text-money"}>
                        {Math.round((picker.orderMargin / picker.costedRevenue) * 100)}%
                      </b>
                    </>
                  )}
                </>
              )}
            </div>
            <div className="flex-1" />
            {confirmingDiscount && (
              <Button variant="secondary" size="sm" onClick={() => setConfirmingDiscount(false)}>
                Отмена
              </Button>
            )}
            {!confirmingDiscount && (
              <Button variant="secondary" size="sm" onClick={onClose}>
                Отмена
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={transfer}
              disabled={busy || !pickedCount}
              icon={<ShoppingCart size={13} />}
            >
              {transferLabel}
            </Button>
          </div>
        </footer>

        {toast && (
          <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-lg bg-ink px-4 py-2 text-[12.5px] font-semibold text-canvas shadow-pop">
            {toast}
          </div>
        )}
      </div>

      {popoverSku && (
        <QtyPricePopover
          sku={popoverSku}
          st={stock[popoverSku.code]}
          whSt={warehouseStock[popoverSku.code]}
          existingQty={rowBySkuId.get(popoverSku.id)?.qty}
          existingPrice={rowBySkuId.get(popoverSku.id)?.priceOverride}
          onCancel={() => setPopoverSku(null)}
          onOk={(qty, price) => {
            // Попап показывает и правит АБСОЛЮТНОЕ количество строки (не «сколько добавить»):
            // для уже существующей строки — setRowQty (перезаписать), для новой — addSkuWithQty
            // (создать). addSkuWithQty суммирует qty только когда его вызывают ПОВТОРНО с ДОБАВКОЙ
            // (напр. клавиатурный ⏎ по кандидату) — здесь так не делаем, чтобы не задвоить.
            if (rowBySkuId.has(popoverSku.id)) {
              picker.setRowQty(popoverSku.id, qty);
            } else {
              addSkuWithQty(popoverSku, qty);
            }
            // Цену пишем ТОЛЬКО если она реально отличается от цены со склада — иначе строка
            // навсегда помечена «✎ отредактировано», хотя пользователь просто подтвердил цену как есть.
            const base = stock[popoverSku.code]?.price;
            setRowPrice(popoverSku.id, base != null && price !== base ? price : undefined);
            setPopoverSku(null);
            flash(`✓ Подобрано: ${popoverSku.title.slice(0, 28)}`);
          }}
        />
      )}
    </div>
  );
}

/**
 * 1С-попап «Ввод количества и цены»: количество, per-warehouse таблица (В резерве/
 * Доступно/Подобрано из groupStockBySku), цена+скидка, «Макс. скидка N%» — потолок
 * скидки, при котором маржа не ниже MIN_MARGIN_FLOOR_PCT. Превышение — не блокирует
 * (согласование РОПа), только подсвечивает.
 */
function QtyPricePopover({
  sku,
  st,
  whSt,
  existingQty,
  existingPrice,
  onCancel,
  onOk,
}: {
  sku: SkuOption;
  st?: SkuStock;
  whSt?: SkuWarehouseStock;
  existingQty?: number;
  /** Уже отредактированная ранее цена строки (PickerRow.priceOverride) — при повторном
   *  открытии попапа показываем ЕЁ, а не сбрасываем на цену со склада. */
  existingPrice?: number;
  onCancel: () => void;
  onOk: (qty: number, price: number) => void;
}) {
  const basePrice = st?.price ?? 0;
  const [qty, setQty] = useState(existingQty ?? 1);
  const [price, setPrice] = useState(existingPrice ?? basePrice);
  const [discount, setDiscount] = useState(
    existingPrice != null && basePrice > 0 ? Math.round((1 - existingPrice / basePrice) * 100 * 10) / 10 : 0,
  );

  const cost = st?.cost ?? null;
  const maxDiscount = cost != null && basePrice > 0 ? Math.max(0, (1 - cost / (1 - MIN_MARGIN_FLOOR_PCT / 100) / basePrice) * 100) : null;
  const currentDiscount = basePrice > 0 ? (1 - price / basePrice) * 100 : 0;
  const overFloor = maxDiscount != null && currentDiscount > maxDiscount + 0.5;
  const m = marginOf({ ...(st ?? { price: 0, cost: null, free: 0, forecast: 0, warehouses: [] }), price });

  function applyDiscount(pct: number) {
    setDiscount(pct);
    setPrice(Math.round(basePrice * (1 - pct / 100)));
  }

  return (
    <div className="fixed inset-0 z-[80]" onClick={onCancel}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="absolute left-1/2 top-1/2 w-[388px] max-w-[94vw] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line-strong bg-surface p-3.5 shadow-pop"
      >
        <div className="text-[13.5px] font-extrabold text-ink">{sku.title}</div>
        <div className="mt-0.5 text-[11px] text-faint">
          арт. {sku.code}
          {m ? (
            <span className="ml-1.5 font-semibold text-money">GP {Math.round(m.pct)}%</span>
          ) : (
            <span className="ml-1.5 font-semibold">маржа —</span>
          )}
        </div>

        <div className="mt-2.5 flex items-center gap-2">
          <span className="w-[74px] shrink-0 text-[11.5px] text-muted">Количество</span>
          <input
            value={qty}
            onChange={(e) => setQty(Math.max(1, parseInt(e.target.value.replace(/\D/g, ""), 10) || 1))}
            inputMode="numeric"
            className="w-[88px] rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-[13px] text-ink outline-none focus:border-accent"
          />
          <span className="text-[11.5px] text-muted">{sku.unit}</span>
        </div>

        {whSt && whSt.rows.length > 0 ? (
          <table className="mt-2.5 w-full border-collapse text-[11.5px]">
            <thead>
              <tr>
                <th className="border-b border-line px-1.5 py-1 text-left text-[9.5px] font-bold uppercase text-faint">Склад</th>
                <th className="border-b border-line px-1.5 py-1 text-right text-[9.5px] font-bold uppercase text-faint">В резерве</th>
                <th className="border-b border-line px-1.5 py-1 text-right text-[9.5px] font-bold uppercase text-faint">Доступно</th>
                <th className="border-b border-line px-1.5 py-1 text-right text-[9.5px] font-bold uppercase text-faint">Подобрано</th>
              </tr>
            </thead>
            <tbody>
              {whSt.rows.map((r) => (
                <tr key={r.warehouse}>
                  <td className="border-b border-line px-1.5 py-1">{r.warehouse}</td>
                  <td className="border-b border-line px-1.5 py-1 text-right font-semibold text-amber-600">{r.reserved || "—"}</td>
                  <td className="border-b border-line px-1.5 py-1 text-right font-bold text-money">{r.free}</td>
                  <td className="border-b border-line px-1.5 py-1 text-right">
                    <button
                      type="button"
                      onClick={() => setQty(r.free || 1)}
                      className="rounded border border-line bg-surface px-1.5 font-bold text-accent-ink hover:bg-accent/10"
                    >
                      {Math.min(qty, r.free)} →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="mt-2.5 text-[11px] text-faint">нет данных по складам — услуга или остаток не пришёл из 1С</div>
        )}

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted">Цена</span>
            <input
              value={price}
              onChange={(e) => {
                const v = parseFloat(e.target.value.replace(/\s/g, "").replace(",", ".")) || 0;
                setPrice(v);
                setDiscount(basePrice > 0 ? Math.round((1 - v / basePrice) * 100 * 10) / 10 : 0);
              }}
              className="w-[74px] rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-[12.5px] text-ink outline-none focus:border-accent"
            />
            <span className="text-[11px] text-muted">Br</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted">Скидка</span>
            <input
              value={discount}
              onChange={(e) => applyDiscount(parseFloat(e.target.value.replace(",", ".")) || 0)}
              className="w-[74px] rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-[12.5px] text-ink outline-none focus:border-accent"
            />
            <span className="text-[11px] text-muted">%</span>
          </div>
          <span
            className={clsx(
              "ml-auto whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] font-bold",
              maxDiscount == null
                ? "bg-sunken text-faint"
                : overFloor
                  ? "bg-red-50 text-danger dark:bg-red-500/10"
                  : "bg-money-soft text-money",
            )}
          >
            {maxDiscount == null ? "Макс. скидка — (нет себеса)" : `Макс. скидка ${Math.floor(maxDiscount)}%`}
          </span>
        </div>

        {overFloor && (
          <p className="mt-1.5 text-[11px] text-danger">
            ⚠ Скидка ниже порога маржи {MIN_MARGIN_FLOOR_PCT}% — на согласование РОПу.
          </p>
        )}

        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-line bg-surface px-3.5 py-2 text-[12.5px] font-bold text-muted hover:bg-sunken"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={() => onOk(qty, price)}
            className="rounded-lg bg-accent px-3.5 py-2 text-[12.5px] font-bold text-white hover:bg-accent-ink"
          >
            ОК
          </button>
        </div>
      </div>
    </div>
  );
}
