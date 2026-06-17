"use client";

import clsx from "clsx";
import { Check, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  approveNorm,
  createNorm,
  deleteNorm,
  fetchNorms,
  filterByKind,
  formatNh,
  type Norm,
  normCounts,
  type NormKind,
  normStatusLabel,
} from "@/lib/production-norms";

const STATUS_STYLES: Record<Norm["status"], string> = {
  none: "bg-sunken text-muted",
  pending: "bg-amber-50 text-amber-600",
  approved: "bg-green-50 text-green-600",
};

const KINDS: { id: NormKind; label: string }[] = [
  { id: "product", label: "Изделия" },
  { id: "operation", label: "Операции" },
];

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export function NormsTable({ initial }: { initial: Norm[] }) {
  const [norms, setNorms] = useState<Norm[]>(initial);
  const [kind, setKind] = useState<NormKind>("product");
  const [title, setTitle] = useState("");
  const [nh, setNh] = useState("");
  const [titleError, setTitleError] = useState(false);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setNorms(await fetchNorms());
  }

  useEffect(() => {
    // первичные данные пришли с SSR; тихо перечитываем на клиенте
    void refresh();
  }, []);

  const rows = useMemo(() => filterByKind(norms, kind), [norms, kind]);
  const counts = useMemo(() => normCounts(norms), [norms]);

  async function onAdd() {
    if (!title.trim()) {
      setTitleError(true);
      setTimeout(() => setTitleError(false), 900);
      return;
    }
    setBusy(true);
    await createNorm({ title: title.trim(), kind, nh: Number(nh.replace(",", ".")) || 0 });
    setTitle("");
    setNh("");
    await refresh();
    setBusy(false);
  }

  async function onApprove(id: number) {
    setBusy(true);
    const ok = await approveNorm(id);
    // 409 для нормы без значения — бэк отказал, просто перечитываем фактическое состояние
    if (ok) await refresh();
    setBusy(false);
  }

  async function onDelete(id: number) {
    setBusy(true);
    await deleteNorm(id);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-3 gap-3">
        <Kpi label="Всего норм" value={counts.total} />
        <Kpi label="На утверждении" value={counts.pending} />
        <Kpi label="Без нормы" value={counts.none} />
      </div>

      <div className="mt-5 inline-flex rounded-lg border border-line bg-sunken p-1">
        {KINDS.map((k) => (
          <button
            key={k.id}
            onClick={() => setKind(k.id)}
            className={clsx(
              "rounded-md px-3 py-1.5 text-sm font-medium",
              kind === k.id ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
            )}
          >
            {k.label}
          </button>
        ))}
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Название</th>
              <th className="px-4 py-2 text-right font-medium">Н.ч</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  Норм этого вида пока нет
                </td>
              </tr>
            )}
            {rows.map((n) => (
              <tr key={n.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-muted">{n.title}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-ink">
                  {formatNh(n.nh)}
                </td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      STATUS_STYLES[n.status],
                    )}
                  >
                    {normStatusLabel(n.status)}
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    {n.status !== "approved" && (
                      <button
                        onClick={() => onApprove(n.id)}
                        disabled={busy}
                        title="Утвердить норму"
                        className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
                      >
                        <Check size={15} />
                      </button>
                    )}
                    <button
                      onClick={() => onDelete(n.id)}
                      disabled={busy}
                      title="Удалить норму"
                      className="flex h-8 w-8 items-center justify-center rounded-lg text-faint hover:bg-red-50 hover:text-red-600 disabled:opacity-60"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex items-center gap-2 border-t border-line px-4 py-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={kind === "product" ? "Название изделия" : "Название операции"}
            className={clsx(
              "min-w-0 flex-1 rounded-lg border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent",
              titleError ? "border-amber-500" : "border-line",
            )}
          />
          <input
            value={nh}
            onChange={(e) => setNh(e.target.value)}
            inputMode="decimal"
            placeholder="Н.ч"
            className="w-20 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            onClick={onAdd}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Plus size={16} /> Добавить
          </button>
        </div>
      </div>
    </div>
  );
}
