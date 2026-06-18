"use client";

import clsx from "clsx";
import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";

import {
  addBomItem,
  approveBom,
  available,
  type Bom,
  bomCounts,
  bomStatusLabel,
  type BomDetail,
  coverageTone,
  createBom,
  deleteBom,
  deleteBomItem,
  fetchBom,
  fetchBoms,
  itemStatusLabel,
  shortItemCount,
} from "@/lib/production-bom";

const STATUS_STYLES: Record<Bom["status"], string> = {
  draft: "bg-sunken text-muted",
  approved: "bg-green-50 text-green-600",
};

const ITEM_STYLES: Record<BomDetail["items"][number]["status"], string> = {
  ok: "bg-green-50 text-green-600",
  short: "bg-red-50 text-red-600",
};

/** Норма расхода в русском формате: 1 → «1», 1.5 → «1,5», дробные склады тоже. */
function num(n: number): string {
  const text = (Math.round(n * 100) / 100).toString().replace(".", ",");
  return text;
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export function BomPanel({ initial }: { initial: Bom[] }) {
  const [boms, setBoms] = useState<Bom[]>(initial);
  const [openId, setOpenId] = useState<number | null>(null);
  const [detail, setDetail] = useState<BomDetail | null>(null);
  const [busy, setBusy] = useState(false);

  // создание спецификации
  const [product, setProduct] = useState("");
  const [version, setVersion] = useState("");
  const [productError, setProductError] = useState(false);

  // добавление позиции в состав
  const [component, setComponent] = useState("");
  const [normQty, setNormQty] = useState("");
  const [unit, setUnit] = useState("");
  const [stock, setStock] = useState("");
  const [reserved, setReserved] = useState("");
  const [componentError, setComponentError] = useState(false);

  async function refreshList() {
    setBoms(await fetchBoms());
  }

  useEffect(() => {
    // первичные данные пришли с SSR; тихо перечитываем на клиенте
    void fetchBoms().then(setBoms);
  }, []);

  const counts = useMemo(() => bomCounts(boms), [boms]);
  const underCovered = useMemo(() => boms.filter((b) => b.coverage < 100).length, [boms]);

  async function loadDetail(id: number) {
    setDetail(await fetchBom(id));
  }

  async function toggle(id: number) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    await loadDetail(id);
  }

  /** перечитать список и (если открыта) деталь — coverage/статус меняются после правок состава */
  async function refreshAll() {
    await refreshList();
    if (openId != null) await loadDetail(openId);
  }

  async function onCreate() {
    if (!product.trim()) {
      setProductError(true);
      setTimeout(() => setProductError(false), 900);
      return;
    }
    setBusy(true);
    await createBom({ product: product.trim(), version: version.trim() || undefined });
    setProduct("");
    setVersion("");
    await refreshList();
    setBusy(false);
  }

  async function onApprove(id: number) {
    setBusy(true);
    // 409 для пустого состава — бэк отказал; просто перечитываем фактическое состояние
    await approveBom(id);
    await refreshAll();
    setBusy(false);
  }

  async function onDelete(id: number) {
    setBusy(true);
    await deleteBom(id);
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
    }
    await refreshList();
    setBusy(false);
  }

  async function onAddItem() {
    if (openId == null) return;
    if (!component.trim()) {
      setComponentError(true);
      setTimeout(() => setComponentError(false), 900);
      return;
    }
    setBusy(true);
    await addBomItem(openId, {
      component: component.trim(),
      norm_qty: Number(normQty.replace(",", ".")) || 0,
      unit: unit.trim() || undefined,
      stock: Number(stock.replace(",", ".")) || 0,
      reserved: Number(reserved.replace(",", ".")) || 0,
    });
    setComponent("");
    setNormQty("");
    setUnit("");
    setStock("");
    setReserved("");
    await refreshAll();
    setBusy(false);
  }

  async function onDeleteItem(itemId: number) {
    setBusy(true);
    await deleteBomItem(itemId);
    await refreshAll();
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="Спецификаций" value={counts.total} />
        <Kpi label="Утверждено" value={counts.approved} />
        <Kpi label="Черновиков" value={counts.draft} />
        <Kpi label="Не обеспечено" value={underCovered} />
      </div>

      <div className="mt-5 text-sm font-semibold text-ink">Справочник спецификаций (BOM)</div>
      <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="w-8 px-2 py-2" />
              <th className="px-4 py-2 font-medium">Изделие</th>
              <th className="px-4 py-2 font-medium">Версия</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Позиций</th>
              <th className="px-4 py-2 text-right font-medium">Обеспеченность</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {boms.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  Спецификаций пока нет
                </td>
              </tr>
            )}
            {boms.map((b) => {
              const open = openId === b.id;
              return (
                <Fragment key={b.id}>
                  <tr
                    className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken"
                    onClick={() => void toggle(b.id)}
                  >
                    <td className="px-2 py-2.5 text-faint">
                      {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </td>
                    <td className="px-4 py-2.5 text-muted">{b.product}</td>
                    <td className="px-4 py-2.5 text-muted">{b.version}</td>
                    <td className="px-4 py-2.5">
                      <span
                        className={clsx(
                          "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                          STATUS_STYLES[b.status],
                        )}
                      >
                        {bomStatusLabel(b.status)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{b.item_count}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span
                        className={clsx(
                          "inline-flex rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums",
                          coverageTone(b.coverage),
                        )}
                      >
                        {b.coverage}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        {b.status !== "approved" && (
                          <button
                            onClick={() => onApprove(b.id)}
                            disabled={busy}
                            title="Утвердить спецификацию"
                            className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
                          >
                            <Check size={15} />
                          </button>
                        )}
                        <button
                          onClick={() => onDelete(b.id)}
                          disabled={busy}
                          title="Удалить спецификацию"
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {open && (
                    <tr className="bg-sunken/60">
                      <td colSpan={7} className="px-4 py-3">
                        <BomComposition
                          detail={detail}
                          loadingFor={b.id}
                          busy={busy}
                          component={component}
                          setComponent={setComponent}
                          componentError={componentError}
                          normQty={normQty}
                          setNormQty={setNormQty}
                          unit={unit}
                          setUnit={setUnit}
                          stock={stock}
                          setStock={setStock}
                          reserved={reserved}
                          setReserved={setReserved}
                          onAddItem={onAddItem}
                          onDeleteItem={onDeleteItem}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>

        <div className="flex items-center gap-2 border-t border-line px-4 py-3">
          <input
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="Изделие новой спецификации"
            className={clsx(
              "min-w-0 flex-1 rounded-lg border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent",
              productError ? "border-amber-500" : "border-line",
            )}
          />
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="Версия (v1)"
            className="w-28 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            onClick={onCreate}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Plus size={16} /> Спецификация
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">
        Любая правка состава возвращает спецификацию в черновик. Позиция «дефицит», если склад
        минус резерв меньше нормы расхода.
      </p>
    </div>
  );
}

interface CompositionProps {
  detail: BomDetail | null;
  loadingFor: number;
  busy: boolean;
  component: string;
  setComponent: (v: string) => void;
  componentError: boolean;
  normQty: string;
  setNormQty: (v: string) => void;
  unit: string;
  setUnit: (v: string) => void;
  stock: string;
  setStock: (v: string) => void;
  reserved: string;
  setReserved: (v: string) => void;
  onAddItem: () => void;
  onDeleteItem: (id: number) => void;
}

function BomComposition(props: CompositionProps) {
  const { detail, loadingFor, busy } = props;

  if (!detail || detail.id !== loadingFor) {
    return <div className="py-2 text-sm text-muted">Загрузка состава…</div>;
  }

  const short = shortItemCount(detail.items);

  return (
    <div>
      <div className="mb-2 flex items-center gap-3 text-xs text-muted">
        <span className="font-medium text-muted">Состав изделия</span>
        <span>позиций: {detail.items.length}</span>
        {short > 0 && <span className="text-red-600">дефицит: {short}</span>}
      </div>
      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-3 py-2 font-medium">Комплектующее</th>
              <th className="px-3 py-2 text-right font-medium">Норма</th>
              <th className="px-3 py-2 text-right font-medium">Склад</th>
              <th className="px-3 py-2 text-right font-medium">Резерв</th>
              <th className="px-3 py-2 text-right font-medium">Доступно</th>
              <th className="px-3 py-2 font-medium">Статус</th>
              <th className="px-3 py-2 text-right font-medium" />
            </tr>
          </thead>
          <tbody>
            {detail.items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-center text-muted">
                  Состав пуст — добавьте комплектующее
                </td>
              </tr>
            )}
            {detail.items.map((it) => (
              <tr key={it.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2 text-muted">{it.component}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">
                  {num(it.norm_qty)} {it.unit}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{num(it.stock)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{num(it.reserved)}</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">
                  {num(available(it))}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      ITEM_STYLES[it.status],
                    )}
                  >
                    {itemStatusLabel(it.status)}
                  </span>
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => props.onDeleteItem(it.id)}
                    disabled={busy}
                    title="Удалить позицию"
                    className="flex h-7 w-7 items-center justify-center rounded-lg text-faint hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2.5">
          <input
            value={props.component}
            onChange={(e) => props.setComponent(e.target.value)}
            placeholder="Комплектующее"
            className={clsx(
              "min-w-0 flex-1 rounded-lg border bg-surface px-3 py-1.5 text-sm text-ink outline-none focus:border-accent",
              props.componentError ? "border-amber-500" : "border-line",
            )}
          />
          <input
            value={props.normQty}
            onChange={(e) => props.setNormQty(e.target.value)}
            inputMode="decimal"
            placeholder="Норма"
            className="w-20 shrink-0 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={props.unit}
            onChange={(e) => props.setUnit(e.target.value)}
            placeholder="Ед."
            className="w-16 shrink-0 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={props.stock}
            onChange={(e) => props.setStock(e.target.value)}
            inputMode="decimal"
            placeholder="Склад"
            className="w-20 shrink-0 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <input
            value={props.reserved}
            onChange={(e) => props.setReserved(e.target.value)}
            inputMode="decimal"
            placeholder="Резерв"
            className="w-20 shrink-0 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            onClick={props.onAddItem}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Plus size={15} /> Позиция
          </button>
        </div>
      </div>
    </div>
  );
}
