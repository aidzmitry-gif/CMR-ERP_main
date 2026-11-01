"use client";

import { Check, PackageCheck, RefreshCw } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { fetchWarehouseProgress, reconcileWarehouseProgress, type ShippingContext, type WarehouseSnapshot } from "@/lib/office-shipping-api";

const labels = { none_recorded: "Выдача пока не зарегистрирована", partial: "Выдача зарегистрирована частично", complete: "Выдача по счёту зарегистрирована полностью" };
const stages: Record<string, string> = { draft: "Черновик", ready: "Готов к подготовке", shipped: "Отгрузка оформлена", docs: "Документы", await_pay: "Ожидание оплаты", paid: "Оплачен" };

export function OfficeWarehouseProgress({ context, disabled, onReconciled }: { context: ShippingContext; disabled: boolean; onReconciled: () => void }) {
  const [snapshot, setSnapshot] = useState<WarehouseSnapshot | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const alive = useRef(true), lock = useRef(false);
  const blocked = useRef(disabled);
  useLayoutEffect(() => { blocked.current = disabled; }, [disabled]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!context.association) return;
    let current = true; const controller = new AbortController();
    void fetchWarehouseProgress(context, controller.signal).then(value => {
      if (current) { setSnapshot(value); setLoading(false); }
    }).catch(e => { if (current && !controller.signal.aborted) { setError(e instanceof Error ? e.message : "Сведения о выдаче недоступны."); setLoading(false); } });
    return () => { current = false; controller.abort(); };
  }, [context, revision]);
  function refresh() { setSnapshot(null); setError(""); setNotice(""); setLoading(true); setRevision(v => v + 1); }
  async function reconcile() {
    if (lock.current || disabled || !snapshot?.can_reconcile) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try {
      const fresh = await fetchWarehouseProgress(context);
      if (!alive.current) return;
      setSnapshot(fresh);
      if (blocked.current) { setNotice("Дождитесь завершения другой команды перед сверкой."); return; }
      if (!fresh.can_reconcile) { setNotice("Сейчас доступно только чтение. Права на сверку изменились."); return; }
      await reconcileWarehouseProgress(context);
      const verified = await fetchWarehouseProgress(context);
      if (alive.current) { setSnapshot(verified); setNotice("Сверка завершена. Показаны сохранённые сведения."); onReconciled(); }
    } catch (e) {
      if (alive.current) { setSnapshot(null); setError(e instanceof Error ? e.message : "Результат сверки нужно проверить."); }
    } finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  const progress = snapshot?.progress;
  return <section className="min-w-0 space-y-4 rounded-xl border border-line bg-surface p-4 sm:p-5" aria-label="Выдача по складам">
    <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2"><PackageCheck size={18} className="shrink-0 text-accent-ink" /><h3 className="font-semibold text-ink">4. Выдача по складам</h3></div><p className="mt-1 text-xs leading-5 text-muted">По связанному счёту и сохранённым актам ERP</p></div>{context.association && <button type="button" disabled={busy || loading} onClick={refresh} className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs text-ink disabled:opacity-50"><RefreshCw size={14} /> Проверить выдачу</button>}</header>
    {!context.association ? <p className="text-sm leading-6 text-muted">Сначала подтвердите связь с точным счётом в блоке 2. Без этой связи сведения о выдаче не запрашиваются.</p> : <>
      {loading && <p role="status" className="text-sm text-muted">Читаем акты выдачи по складам…</p>}
      {error && <div role="alert" className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><p>{error}</p><p className="text-xs leading-5">Отсутствие ответа не означает отсутствие выдачи. Проверьте сведения; автоматического повтора сверки нет.</p><button type="button" disabled={busy} onClick={refresh} className="rounded-lg border border-amber-300 px-3 py-2 font-medium">Перечитать сведения</button></div>}
      {notice && <p role="status" className="flex items-start gap-2 text-sm text-emerald-800"><Check size={16} className="mt-0.5 shrink-0" />{notice}</p>}
      {snapshot && progress && <>
        <div className={`rounded-lg border p-4 ${progress.state === "complete" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-line bg-sunken text-ink"}`}><p className="font-semibold">{labels[progress.state]}</p><p className="mt-1 text-xs leading-5">Этап документа: {stages[snapshot.document_stage] || snapshot.document_stage}. Оплата и доставка перевозчиком проверяются отдельно.</p></div>
        <div className="space-y-3">{progress.lines.map(row => <article key={row.source} className="min-w-0 rounded-lg border border-line p-3 sm:p-4"><div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 break-words text-sm font-semibold text-ink">{row.sku_code}<span className="ml-2 font-normal text-muted">Строка {row.line_no}</span></p><span className="max-w-full break-words rounded-md bg-accent-soft px-2 py-1 text-xs font-medium text-accent-ink">Склад {row.warehouse}</span></div><dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">{[["По счёту", row.expected_qty], ["Выдано", row.shipped_qty], ["В резерве", row.reserved_qty], ["Резерв снят", row.released_qty]].map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-all text-sm font-semibold tabular-nums text-ink">{value}</dd></div>)}</dl></article>)}</div>
        {progress.lines.some(row => row.released_qty !== "0.00") && <p className="rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-900">Снятый резерв не считается выдачей. Сверьте основание снятия и оставшееся количество.</p>}
        {progress.acts.length > 0 && <details className="rounded-lg border border-line p-3 text-xs text-muted"><summary className="cursor-pointer font-medium text-ink">Акты выдачи · {progress.acts.length}</summary><ul className="mt-3 space-y-2">{progress.acts.map(act => <li key={act.act_id} className="break-words">Акт #{act.act_id} · {act.operation_date} · {act.execution_mode === "document" ? "Документальный режим: без подтверждения на устройстве" : "Режим складской выдачи"}</li>)}</ul></details>}
        <div className="space-y-3 border-t border-line pt-4"><p className="text-xs leading-5 text-muted">Сверка обновляет сведения и этап этого документа по сохранённым актам. Новая выдача товара не оформляется.</p>{snapshot.can_reconcile ? <button type="button" onClick={() => void reconcile()} disabled={busy || disabled} className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"><RefreshCw size={16} />{busy ? "Сверяем…" : "Сверить документ с актами"}</button> : <p className="text-sm text-muted">Доступно только чтение. Для сверки требуется действующее право изменения этапа документа.</p>}</div>
      </>}
      <p className="text-xs leading-5 text-muted">Здесь показаны записи связанного счёта в ERP. Полнота сведений из 1С и других источников не подтверждена. Внутренний акт не заменяет ТН/ТТН и подтверждение передачи груза.</p>
    </>}
  </section>;
}
