"use client";

import { Check, Gavel, X } from "lucide-react";
import { useEffect, useState } from "react";
import { type Approval, decideApproval, fetchApprovals, requestApproval } from "@/lib/api";

const KINDS = [
  { value: "deal.contract", label: "Договор → Юрист" },
  { value: "deal.discount", label: "Скидка → РОП" },
  { value: "payment.large", label: "Платёж → Главбух" },
];

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "На согласовании", cls: "bg-amber-50 text-amber-600" },
  approved: { label: "Согласовано", cls: "bg-emerald-50 text-emerald-600" },
  rejected: { label: "Отклонено", cls: "bg-red-50 text-red-600" },
};

export function DealApprovals({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<Approval[]>([]);
  const [kind, setKind] = useState(KINDS[0].value);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchApprovals({ entityRef: `deal:${dealId}` }));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function onRequest() {
    setBusy(true);
    await requestApproval(dealId, kind);
    await refresh();
    setBusy(false);
  }

  async function onDecide(id: number, approved: boolean) {
    setBusy(true);
    await decideApproval(id, approved, "Согласующий");
    await refresh();
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-xl border border-slate-200 p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <Gavel size={18} className="text-brand-600" /> Согласования
      </div>

      <div className="mt-3 flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <button
          onClick={onRequest}
          disabled={busy}
          className="shrink-0 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          На согласование
        </button>
      </div>

      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="text-sm text-muted">Пока нет согласований</li>}
        {items.map((a) => {
          const s = STATUS[a.status] ?? STATUS.pending;
          return (
            <li
              key={a.id}
              className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-ink">
                  {a.kind} · {a.route}
                </div>
                <span className={`mt-0.5 inline-block rounded-md px-2 py-0.5 text-xs font-medium ${s.cls}`}>
                  {s.label}
                  {a.decided_by ? ` · ${a.decided_by}` : ""}
                </span>
              </div>
              {a.status === "pending" && (
                <div className="flex shrink-0 gap-1.5">
                  <button
                    onClick={() => onDecide(a.id, true)}
                    disabled={busy}
                    title="Согласовать"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
                  >
                    <Check size={16} />
                  </button>
                  <button
                    onClick={() => onDecide(a.id, false)}
                    disabled={busy}
                    title="Отклонить"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100"
                  >
                    <X size={16} />
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
