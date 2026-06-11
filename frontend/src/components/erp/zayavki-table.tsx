"use client";

import clsx from "clsx";
import { AlertTriangle, Play, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PriorityBadge } from "@/components/priority-badge";
import { coverageTone, fetchBoms } from "@/lib/production-bom";
import { fetchNorms } from "@/lib/production-norms";
import {
  type Bom,
  coverageForProduct,
  createOrder,
  fetchOrders,
  formatNh,
  type Norm,
  nhTotal,
  normForProduct,
  type Order,
  type Stage,
  STAGES,
  stageLabel,
  stageTone,
  updateOrderStage,
  zayavkiCounts,
} from "@/lib/production-zayavki";
import type { Priority } from "@/lib/types";

const PRIORITIES: Priority[] = ["Высокий", "Средний", "Низкий"];
const SEGMENTS: { id: Stage | "all"; label: string }[] = [{ id: "all", label: "Все" }, ...STAGES];

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export function ZayavkiTable({
  initialOrders,
  initialNorms,
  initialBoms,
}: {
  initialOrders: Order[];
  initialNorms: Norm[];
  initialBoms: Bom[];
}) {
  const [orders, setOrders] = useState<Order[]>(initialOrders);
  const [norms, setNorms] = useState<Norm[]>(initialNorms);
  const [boms, setBoms] = useState<Bom[]>(initialBoms);
  const [seg, setSeg] = useState<Stage | "all">("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  // создание заявки
  const [product, setProduct] = useState("");
  const [qty, setQty] = useState("");
  const [priority, setPriority] = useState<Priority>("Средний");
  const [due, setDue] = useState("");
  const [productError, setProductError] = useState(false);

  async function refresh() {
    const [o, n, b] = await Promise.all([fetchOrders(), fetchNorms(), fetchBoms()]);
    setOrders(o);
    setNorms(n);
    setBoms(b);
  }

  useEffect(() => {
    // первичные данные пришли с SSR; тихо перечитываем на клиенте
    void refresh();
  }, []);

  const counts = useMemo(() => zayavkiCounts(orders, norms, boms), [orders, norms, boms]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return orders.filter((o) => {
      if (seg !== "all" && o.stage !== seg) return false;
      if (!q) return true;
      return o.number.toLowerCase().includes(q) || o.product.toLowerCase().includes(q);
    });
  }, [orders, seg, query]);

  async function onCreate() {
    if (!product.trim()) {
      setProductError(true);
      setTimeout(() => setProductError(false), 900);
      return;
    }
    setBusy(true);
    await createOrder({
      product: product.trim(),
      qty: Number(qty) || 1,
      priority,
      due_date: due.trim() || undefined,
    });
    setProduct("");
    setQty("");
    setDue("");
    await refresh();
    setBusy(false);
  }

  async function onLaunch(id: number) {
    setBusy(true);
    await updateOrderStage(id, "assembly");
    await refresh();
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="Заявок всего" value={counts.total} />
        <Kpi label="Без нормы" value={counts.withoutNorm} />
        <Kpi label="Без BOM" value={counts.withoutBom} />
        <Kpi label="В работе" value={counts.inProgress} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="inline-flex flex-wrap rounded-lg border border-slate-200 bg-slate-50 p-1">
          {SEGMENTS.map((s) => (
            <button
              key={s.id}
              onClick={() => setSeg(s.id)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium",
                seg === s.id ? "bg-white text-brand shadow-sm" : "text-slate-500",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="relative ml-auto">
          <Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по № или изделию"
            className="w-64 rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-brand"
          />
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">№</th>
              <th className="px-4 py-2 font-medium">Изделие</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 text-right font-medium">Н.ч итого</th>
              <th className="px-4 py-2 font-medium">Ответственный</th>
              <th className="px-4 py-2 font-medium">Срок</th>
              <th className="px-4 py-2 font-medium">Приоритет</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Обеспеченность</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={10} className="px-4 py-6 text-center text-muted">
                  {orders.length === 0 ? "Заявок пока нет" : "Ничего не найдено"}
                </td>
              </tr>
            )}
            {rows.map((o) => {
              const norm = normForProduct(norms, o.product);
              const coverage = coverageForProduct(boms, o.product);
              const launchable = o.stage === "queue" && norm != null;
              return (
                <tr key={o.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-4 py-2.5 font-medium text-slate-700">{o.number}</td>
                  <td className="px-4 py-2.5 text-slate-700">
                    <span className="inline-flex items-center gap-1.5">
                      {o.product}
                      {norm == null && (
                        <span
                          title="Нет утверждённой нормы по изделию"
                          className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-600"
                        >
                          <AlertTriangle size={11} /> нет нормы
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-slate-600">{o.qty}</td>
                  <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-ink">
                    {formatNh(nhTotal(o))}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{o.owner || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-600">{o.due_date || "—"}</td>
                  <td className="px-4 py-2.5">
                    <PriorityBadge priority={o.priority as Priority} />
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={clsx(
                        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                        stageTone(o.stage),
                      )}
                    >
                      {stageLabel(o.stage)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {coverage == null ? (
                      <span className="text-xs text-slate-400">нет BOM</span>
                    ) : (
                      <span
                        className={clsx(
                          "inline-flex rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums",
                          coverageTone(coverage),
                        )}
                      >
                        {coverage}%
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end">
                      {o.stage === "queue" && (
                        <button
                          onClick={() => onLaunch(o.id)}
                          disabled={busy || !launchable}
                          title={launchable ? "Запустить в работу" : "Нет нормы — запуск недоступен"}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-brand-50 hover:text-brand disabled:opacity-50"
                        >
                          <Play size={13} /> В работу
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3">
          <input
            value={product}
            onChange={(e) => setProduct(e.target.value)}
            placeholder="Изделие новой заявки"
            className={clsx(
              "min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:border-brand",
              productError ? "border-amber-500" : "border-slate-200",
            )}
          />
          <input
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            inputMode="numeric"
            placeholder="Кол-во"
            className="w-20 shrink-0 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
          />
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as Priority)}
            className="shrink-0 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <input
            value={due}
            onChange={(e) => setDue(e.target.value)}
            placeholder="Срок"
            className="w-28 shrink-0 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
          />
          <button
            onClick={onCreate}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            <Plus size={16} /> Заявка
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">
        Заявка = производственный наряд в ранних этапах. «В работу» переводит наряд из очереди в
        сборку (доступно при утверждённой норме по изделию).
      </p>
    </div>
  );
}
