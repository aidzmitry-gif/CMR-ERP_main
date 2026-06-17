"use client";

import { Check, FileText, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createDocument, type DealDoc, decideDocument, fetchDocuments } from "@/lib/api";

const KINDS = [
  { value: "invoice", label: "Счёт" },
  { value: "contract", label: "Договор" },
  { value: "order", label: "Заказ" },
];

const KIND_LABEL: Record<string, string> = {
  invoice: "Счёт",
  contract: "Договор",
  order: "Заказ",
};

const STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "Черновик", cls: "bg-sunken text-muted" },
  pending_approval: { label: "На согласовании", cls: "bg-amber-50 text-amber-600" },
  posted: { label: "Записан в 1С", cls: "bg-emerald-50 text-emerald-600" },
  rejected: { label: "Отклонён", cls: "bg-red-50 text-red-600" },
};

export function DealDocuments({ dealId }: { dealId: string }) {
  const [items, setItems] = useState<DealDoc[]>([]);
  const [kind, setKind] = useState(KINDS[0].value);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setItems(await fetchDocuments(dealId));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function onCreate() {
    setBusy(true);
    await createDocument(dealId, kind);
    await refresh();
    setBusy(false);
  }

  async function onDecide(docId: number, approved: boolean) {
    setBusy(true);
    await decideDocument(docId, approved, "Юрист");
    await refresh();
    setBusy(false);
  }

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <FileText size={18} className="text-accent-ink" /> Документы
      </div>

      <div className="mt-3 flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        >
          {KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
        <button
          onClick={onCreate}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          <Plus size={16} /> Сформировать
        </button>
      </div>

      <ul className="mt-3 space-y-2">
        {items.length === 0 && <li className="text-sm text-muted">Документов пока нет</li>}
        {items.map((d) => {
          const s = STATUS[d.status] ?? STATUS.draft;
          return (
            <li
              key={d.id}
              className="flex items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-ink">
                  {KIND_LABEL[d.kind] ?? d.kind} · {d.number}
                </div>
                <span className={`mt-0.5 inline-block rounded-md px-2 py-0.5 text-xs font-medium ${s.cls}`}>
                  {s.label}
                  {d.onec_ref ? ` · ${d.onec_ref}` : ""}
                </span>
              </div>
              {d.status === "pending_approval" && (
                <div className="flex shrink-0 gap-1.5">
                  <button
                    onClick={() => onDecide(d.id, true)}
                    disabled={busy}
                    title="Согласовать и провести в 1С"
                    className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
                  >
                    <Check size={16} />
                  </button>
                  <button
                    onClick={() => onDecide(d.id, false)}
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
