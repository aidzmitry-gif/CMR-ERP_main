"use client";

import clsx from "clsx";
import { CheckCircle2, Lock } from "lucide-react";
import { useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  acceptReceipt,
  fetchReceipt,
  qcReceipt,
  type ReceiptDetail,
  receiptStatusLabel,
} from "@/lib/wms-warehouse";

export function WmsReceiptDetail({ initial }: { initial: ReceiptDetail }) {
  const [doc, setDoc] = useState<ReceiptDetail>(initial);
  const [drafts, setDrafts] = useState<Record<number, { acc: string; rej: string; reason: string }>>({});
  const [busy, setBusy] = useState(false);
  const locked = doc.status !== "pending_qc";

  async function refresh() {
    const fresh = await fetchReceipt(doc.id);
    if (fresh) setDoc(fresh);
  }

  function draft(id: number) {
    const line = doc.lines.find((l) => l.id === id)!;
    return drafts[id] ?? {
      acc: line.accepted_qty === null ? "" : String(line.accepted_qty),
      rej: line.rejected_qty === null ? "" : String(line.rejected_qty),
      reason: line.reject_reason,
    };
  }

  async function saveQc() {
    setBusy(true);
    const decisions = doc.lines.map((l) => {
      const d = draft(l.id);
      return {
        line_id: l.id,
        accepted_qty: Number(d.acc.replace(",", ".")) || 0,
        rejected_qty: Number(d.rej.replace(",", ".")) || 0,
        reject_reason: d.reason,
      };
    });
    await qcReceipt(doc.id, decisions);
    setDrafts({});
    await refresh();
    setBusy(false);
  }

  async function onAccept() {
    setBusy(true);
    await acceptReceipt(doc.id);
    await refresh();
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-ink">{doc.number}</h1>
            <span className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium",
              locked ? "bg-green-50 text-green-600" : "bg-amber-50 text-amber-600")}>
              {locked && <Lock size={11} />} {receiptStatusLabel(doc.status)}
            </span>
          </div>
          <p className="mt-0.5 text-sm text-muted">
            Склад {doc.warehouse} · основание {doc.entity_ref || "—"}
          </p>
        </div>
        {!locked && (
          <div className="flex items-center gap-2">
            <button onClick={saveQc} disabled={busy}
              className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60">
              Сохранить QC
            </button>
            <button onClick={onAccept} disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
              <CheckCircle2 size={15} /> Принять (приход)
            </button>
          </div>
        )}
      </div>

      {locked && (
        <div className="mt-4 rounded-xl border border-line bg-sunken px-4 py-3 text-sm text-muted">
          Приёмка проведена: приход записан по принятому кол-ву, брак на свободный остаток не попал.
          Авто-создана задача размещения (put-away).
        </div>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 text-right font-medium">Ожидается</th>
              <th className="px-4 py-2 text-right font-medium">Принято</th>
              <th className="px-4 py-2 text-right font-medium">Брак</th>
              <th className="px-4 py-2 font-medium">Причина брака</th>
            </tr>
          </thead>
          <tbody>
            {doc.lines.map((l) => {
              const d = draft(l.id);
              return (
                <tr key={l.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{l.sku_code}</td>
                  <td className="px-4 py-2.5 text-ink">{l.sku_title || "—"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(l.expected_qty)}</td>
                  {locked ? (
                    <>
                      <td className="px-4 py-2.5 text-right tabular-nums text-green-600">
                        {l.accepted_qty === null ? "—" : formatNumber(l.accepted_qty)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-red-600">
                        {l.rejected_qty ? formatNumber(l.rejected_qty) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-faint">{l.reject_reason || "—"}</td>
                    </>
                  ) : (
                    <>
                      <td className="px-4 py-2.5 text-right">
                        <input value={d.acc} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, acc: e.target.value } }))}
                          inputMode="decimal" placeholder="0"
                          className="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-accent" />
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <input value={d.rej} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, rej: e.target.value } }))}
                          inputMode="decimal" placeholder="0"
                          className="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-accent" />
                      </td>
                      <td className="px-4 py-2.5">
                        <input value={d.reason} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, reason: e.target.value } }))}
                          placeholder="напр. бой"
                          className="w-full rounded-lg border border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent" />
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
