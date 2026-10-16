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
  const [error, setError] = useState("");
  const locked = doc.status !== "pending_qc";

  async function refresh() {
    const fresh = await fetchReceipt(doc.id);
    if (!fresh) throw new Error("Не удалось обновить документ. Изменения могли сохраниться; повторите загрузку перед проведением.");
    setDoc(fresh);
  }

  function draft(id: number) {
    const line = doc.lines.find((l) => l.id === id)!;
    return drafts[id] ?? {
      acc: line.accepted_qty === null ? "" : String(line.accepted_qty),
      rej: line.rejected_qty === null ? "0" : String(line.rejected_qty),
      reason: line.reject_reason,
    };
  }

  async function saveQc() {
    if (busy) return;
    setError("");
    function quantity(value: string) {
      const normalized = value.trim().replace(",", ".");
      if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(normalized)) throw new Error("Введите количество явно: неотрицательное число, до двух знаков после запятой.");
      return normalized;
    }
    try {
      const decisions = doc.lines.map((l) => {
      const d = draft(l.id);
      return {
        line_id: l.id,
        accepted_qty: quantity(d.acc),
        rejected_qty: quantity(d.rej),
        reject_reason: d.reason,
      };
      });
      setBusy(true);
      if (!await qcReceipt(doc.id, decisions, "", doc.qc_revision)) throw new Error("Не удалось сохранить контроль качества. Документ мог измениться или доступ ограничен. Введённые данные остаются в форме; сравните их с актуальным документом перед повтором.");
      await refresh();
      setDrafts({});
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить контроль качества."); }
    finally { setBusy(false); }
  }

  async function onAccept() {
    if (busy) return;
    if (Object.keys(drafts).length) { setError("Сначала сохраните введённые результаты контроля качества."); return; }
    setBusy(true);
    setError("");
    try {
      if (!await acceptReceipt(doc.id)) throw new Error("Не удалось провести приёмку. Проверьте доступ и состояние документа.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось провести приёмку."); }
    finally { setBusy(false); }
  }

  async function refreshForReview() {
    if (busy) return;
    setBusy(true); setError("");
    try { await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось обновить документ."); }
    finally { setBusy(false); }
  }

  return (
    <div className="min-w-0 w-0 flex-1 overflow-auto p-6 lg:pr-24">
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
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
            <button onClick={() => void refreshForReview()} disabled={busy} className="rounded-lg border border-line px-3 py-2 text-sm">Обновить данные для сравнения</button>
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
                        <input aria-label={`Принято ${l.sku_code}`} disabled={busy} value={d.acc} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, acc: e.target.value } }))}
                          inputMode="decimal" placeholder="0"
                          className="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-accent" />
                        <small className="block text-muted">В документе: {l.accepted_qty ?? "не задано"}</small>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <input aria-label={`Брак ${l.sku_code}`} disabled={busy} value={d.rej} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, rej: e.target.value } }))}
                          inputMode="decimal" placeholder="0"
                          className="w-16 rounded-lg border border-line bg-surface px-2 py-1 text-right text-sm tabular-nums outline-none focus:border-accent" />
                        <small className="block text-muted">В документе: {l.rejected_qty ?? "не задано"}</small>
                      </td>
                      <td className="px-4 py-2.5">
                        <input aria-label={`Причина брака ${l.sku_code}`} disabled={busy} value={d.reason} onChange={(e) => setDrafts((s) => ({ ...s, [l.id]: { ...d, reason: e.target.value } }))}
                          placeholder="напр. бой"
                          className="w-full rounded-lg border border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent" />
                        <small className="block text-muted">В документе: {l.reject_reason || "не указана"}</small>
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
