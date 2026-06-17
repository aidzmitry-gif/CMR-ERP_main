"use client";

import { Trash2 } from "lucide-react";
import { useCallback, useState } from "react";

import {
  deletePosition,
  fmtNh,
  loadTone,
  type PlanBoard,
  type PlanCellUpdate,
  putPlanCell,
  upsertPosition,
} from "@/lib/production-plan";

const MONTHS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

interface Props {
  initial: PlanBoard | null;
}

export function PlanMatrix({ initial }: Props) {
  const [board, setBoard] = useState<PlanBoard | null>(initial);
  const [year, setYear] = useState(initial?.year ?? new Date().getFullYear());
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editVal, setEditVal] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newProduct, setNewProduct] = useState("");
  const [newMonthly, setNewMonthly] = useState<string[]>(Array(12).fill("0"));
  const [loading, setLoading] = useState(false);

  const loadYear = useCallback(async (y: number) => {
    setLoading(true);
    const { fetchPlan } = await import("@/lib/production-plan");
    const b = await fetchPlan(y);
    setBoard(b);
    setYear(y);
    setLoading(false);
  }, []);

  const handleCellClick = (product: string, month: number, currentQty: number) => {
    setEditKey(`${product}:${month}`);
    setEditVal(String(currentQty));
  };

  const handleCellBlur = async (update: PlanCellUpdate) => {
    setEditKey(null);
    const qty = Math.max(0, parseInt(editVal, 10) || 0);
    if (qty === update.plan_qty) return;
    setLoading(true);
    const b = await putPlanCell({ ...update, plan_qty: qty });
    if (b) setBoard(b);
    setLoading(false);
  };

  const handleDelete = async (product: string) => {
    if (!board) return;
    setLoading(true);
    const ok = await deletePosition(board.year, product);
    if (ok) {
      const b = await import("@/lib/production-plan").then((m) => m.fetchPlan(board.year));
      if (b) setBoard(b);
    }
    setLoading(false);
  };

  const handleAddPosition = async () => {
    if (!newProduct.trim() || !board) return;
    const monthly = newMonthly.map((v) => Math.max(0, parseInt(v, 10) || 0));
    setLoading(true);
    const b = await upsertPosition({ year: board.year, product: newProduct.trim(), monthly });
    if (b) {
      setBoard(b);
      setShowAddForm(false);
      setNewProduct("");
      setNewMonthly(Array(12).fill("0"));
    }
    setLoading(false);
  };

  if (!board) {
    return (
      <div className="p-6 text-muted text-sm">
        Данные планирования недоступны. Проверьте соединение с сервером.
      </div>
    );
  }

  const { totals, rows, capacity_nh } = board;
  const maxBarNh = Math.max(...totals.month_nh, ...totals.fact_nh, capacity_nh, 1);

  return (
    <div className="space-y-6">
      {/* Header: year nav + KPI */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => loadYear(year - 1)}
            className="px-3 py-1 text-sm border border-line rounded hover:bg-sunken"
          >
            ‹
          </button>
          <span className="font-semibold text-lg">{year}</span>
          <button
            onClick={() => loadYear(year + 1)}
            className="px-3 py-1 text-sm border border-line rounded hover:bg-sunken"
          >
            ›
          </button>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <div className="bg-sunken rounded px-3 py-1">
            <span className="text-muted">Мощность:</span>{" "}
            <span className="font-medium">{fmtNh(capacity_nh)} н.ч/мес</span>
          </div>
          <div className="bg-blue-50 rounded px-3 py-1">
            <span className="text-muted">План YTD:</span>{" "}
            <span className="font-medium text-blue-700">{fmtNh(totals.plan_ytd)} н.ч</span>
          </div>
          <div className="bg-green-50 rounded px-3 py-1">
            <span className="text-muted">Факт YTD:</span>{" "}
            <span className="font-medium text-green-700">{fmtNh(totals.fact_ytd)} н.ч</span>
          </div>
          <div className={`rounded px-3 py-1 ${loadTone(totals.load_pct[totals.peak_month] ?? 0)}`}>
            <span>Пик: {MONTHS[totals.peak_month]}</span>
          </div>
        </div>
      </div>

      {loading && <div className="text-xs text-faint">Загрузка…</div>}

      {/* Matrix table */}
      <div className="overflow-x-auto rounded border border-line">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="bg-sunken border-b border-line">
              <th className="text-left px-3 py-2 font-medium text-muted w-48">Изделие</th>
              {MONTHS.map((m) => (
                <th key={m} className="text-center px-1 py-2 font-medium text-muted min-w-[52px]">
                  {m}
                </th>
              ))}
              <th className="text-center px-2 py-2 font-medium text-muted">Итого</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.product} className="border-b border-line hover:bg-sunken">
                <td className="px-3 py-1.5 text-muted font-medium truncate max-w-[192px]">
                  {row.product}
                  {row.norm_nh > 0 && (
                    <span className="ml-1 text-faint font-normal">
                      ({fmtNh(row.norm_nh)} н.ч)
                    </span>
                  )}
                </td>
                {row.months.map((cell) => {
                  const key = `${row.product}:${cell.month}`;
                  const isEditing = editKey === key;
                  const tone = loadTone(totals.load_pct[cell.month - 1] ?? 0);
                  return (
                    <td key={cell.month} className="px-1 py-1 text-center">
                      {isEditing ? (
                        <input
                          type="number"
                          min={0}
                          className="w-12 text-center border border-line rounded px-1 py-0.5 text-xs bg-surface text-ink"
                          value={editVal}
                          onChange={(e) => setEditVal(e.target.value)}
                          onBlur={() =>
                            handleCellBlur({
                              year: board.year,
                              product: row.product,
                              month: cell.month,
                              plan_qty: cell.plan_qty,
                            })
                          }
                          autoFocus
                        />
                      ) : (
                        <button
                          onClick={() => handleCellClick(row.product, cell.month, cell.plan_qty)}
                          className={`w-12 rounded px-1 py-0.5 text-center ${cell.plan_qty > 0 ? tone : "text-faint"} hover:ring-1 hover:ring-blue-300`}
                          title={`план: ${cell.plan_qty} шт / факт: ${cell.fact_qty} шт`}
                        >
                          {cell.plan_qty || "—"}
                        </button>
                      )}
                    </td>
                  );
                })}
                <td className="px-2 py-1 text-center font-medium text-ink">
                  {row.year_qty}
                </td>
                <td className="px-1 py-1">
                  <button
                    onClick={() => handleDelete(row.product)}
                    className="text-faint hover:text-red-500 p-0.5"
                    title="Удалить позицию"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}

            {/* Totals row: plan н.ч */}
            <tr className="border-b border-line bg-blue-50">
              <td className="px-3 py-1.5 text-muted font-medium">Σ план н.ч</td>
              {totals.month_nh.map((nh, i) => (
                <td key={i} className="px-1 py-1 text-center text-blue-700 font-medium">
                  {fmtNh(nh)}
                </td>
              ))}
              <td className="px-2 py-1 text-center text-blue-700 font-medium">
                {fmtNh(totals.year_nh)}
              </td>
              <td></td>
            </tr>

            {/* Fact row */}
            <tr className="border-b border-line bg-green-50">
              <td className="px-3 py-1.5 text-muted font-medium">Σ факт н.ч</td>
              {totals.fact_nh.map((nh, i) => (
                <td key={i} className="px-1 py-1 text-center text-green-700 font-medium">
                  {fmtNh(nh)}
                </td>
              ))}
              <td className="px-2 py-1 text-center text-green-700 font-medium">
                {fmtNh(totals.fact_nh.reduce((a, b) => a + b, 0))}
              </td>
              <td></td>
            </tr>

            {/* Load % row */}
            <tr className="bg-sunken">
              <td className="px-3 py-1.5 text-muted font-medium">Загрузка %</td>
              {totals.load_pct.map((pct, i) => (
                <td key={i} className="px-1 py-1 text-center">
                  <span className={`rounded px-1 py-0.5 text-xs font-medium ${loadTone(pct)}`}>
                    {pct.toFixed(0)}%
                  </span>
                </td>
              ))}
              <td></td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Capacity chart */}
      <div>
        <h3 className="text-sm font-medium text-ink mb-3">График мощности (н.ч)</h3>
        <div className="flex items-end gap-2 h-32 border-b border-line pb-1">
          {MONTHS.map((m, i) => {
            const planH = Math.round((totals.month_nh[i] / maxBarNh) * 100);
            const factH = Math.round((totals.fact_nh[i] / maxBarNh) * 100);
            const tone = loadTone(totals.load_pct[i] ?? 0);
            return (
              <div key={m} className="flex-1 flex flex-col items-center gap-0.5">
                <div className="w-full flex items-end gap-0.5 h-24">
                  <div
                    className={`flex-1 rounded-t ${tone} opacity-80`}
                    style={{ height: `${planH}%`, minHeight: planH > 0 ? "2px" : "0" }}
                    title={`план: ${fmtNh(totals.month_nh[i])} н.ч`}
                  />
                  <div
                    className="flex-1 rounded-t bg-green-400 opacity-70"
                    style={{ height: `${factH}%`, minHeight: factH > 0 ? "2px" : "0" }}
                    title={`факт: ${fmtNh(totals.fact_nh[i])} н.ч`}
                  />
                </div>
                <span className="text-xs text-faint">{m}</span>
              </div>
            );
          })}
        </div>
        <div className="flex gap-4 mt-1 text-xs text-muted">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-amber-200 rounded-sm" /> план
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-green-400 rounded-sm" /> факт
          </span>
        </div>
      </div>

      {/* Add position */}
      <div>
        {showAddForm ? (
          <div className="border border-line rounded p-4 space-y-3 bg-sunken">
            <div className="flex items-center gap-2">
              <label className="text-sm font-medium text-muted w-24">Изделие</label>
              <input
                type="text"
                className="flex-1 border border-line rounded px-2 py-1 text-sm bg-surface text-ink"
                placeholder="Название изделия"
                value={newProduct}
                onChange={(e) => setNewProduct(e.target.value)}
              />
            </div>
            <div>
              <label className="text-sm font-medium text-muted block mb-1">
                Плановое кол-во по месяцам (шт)
              </label>
              <div className="grid grid-cols-12 gap-1">
                {MONTHS.map((m, i) => (
                  <div key={m} className="flex flex-col items-center">
                    <span className="text-xs text-faint mb-0.5">{m}</span>
                    <input
                      type="number"
                      min={0}
                      className="w-full border border-line rounded px-1 py-0.5 text-xs text-center bg-surface text-ink"
                      value={newMonthly[i]}
                      onChange={(e) => {
                        const next = [...newMonthly];
                        next[i] = e.target.value;
                        setNewMonthly(next);
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleAddPosition}
                disabled={!newProduct.trim() || loading}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                Добавить
              </button>
              <button
                onClick={() => setShowAddForm(false)}
                className="px-3 py-1.5 text-sm border border-line rounded hover:bg-sunken"
              >
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowAddForm(true)}
            className="text-sm text-blue-600 hover:underline"
          >
            + Добавить позицию
          </button>
        )}
      </div>
    </div>
  );
}
