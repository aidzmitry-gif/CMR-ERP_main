"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { documentStatusLabels, reservationStatusLabels } from "@/lib/document-status-labels";
import type { LossReason } from "@/lib/types";
import { fetchLossReasons } from "@/lib/api";
import { beginLossCommand, dispatchLoss, fetchLossContext, fetchLossPreview, fetchLossProgress,
  readLossJournal, recoverLoss, requireScope, scopeOf, type Journal, type LossContext, type LossPreview,
  type LossRecord, type LossResolution, type LossAttempt, type RequestBody, type ResolveBody } from "@/lib/deal-loss-api";

const blockerLabels: Record<string, string> = {
  chief_invoice_cancellation_required: "Главному бухгалтеру нужно подтвердить аннулирование счёта.",
  funds_not_fully_refunded: "Полученную оплату нужно полностью вернуть перед аннулированием.",
  funds_not_fully_refunded_or_history_unknown: "Оплата возвращена не полностью либо история оплат ещё не сверена.",
  money_not_fully_refunded_or_unknown: "Оплата возвращена не полностью либо история оплат ещё не сверена.",
  physical_shipment_requires_return_workflow: "Товар уже отгружен: сначала оформите его возврат.",
  accounting_fulfillment_classification_required: "Бухгалтеру нужно сверить документы исполнения счёта.",
  unexecuted_logistics_withdrawal_required: "Нужно подтвердить остановку запланированной перевозки или торгов.",
  cancelled_invoice_money_review_required: "Нужно сверить оплаты и возвраты по аннулированному счёту.",
  missing_or_inconsistent_invoice_history: "История счёта неполная или содержит расхождения — нужна сверка.",
};

const INPUT = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink";
const BUTTON = "rounded-lg border border-line px-3 py-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed";
const message = (e: unknown) => e instanceof Error ? e.message : "Не удалось проверить запрос отказа.";

export function DealLossControl({ dealId, dealLabel }: { dealId: string; dealLabel: string }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  return <><button className={BUTTON} onClick={() => setOpen(true)}>Отказ / состояние запроса</button>
    {open && <LoseDealModal key={dealId} dealId={dealId} dealLabel={dealLabel} onCancel={() => setOpen(false)}
      onFinalized={() => router.refresh()} />}</>;
}

export function LoseDealModal({ dealId, dealLabel, reasons: suppliedReasons, onCancel, onFinalized, onPending }: {
  dealId: string; dealLabel: string; reasons?: LossReason[]; onCancel: () => void;
  onFinalized?: (receipt: LossResolution, record: LossRecord) => void; onPending?: (requestId: string | null) => void;
}) {
  const [ctx, setCtx] = useState<LossContext | null>(null);
  const [preview, setPreview] = useState<LossPreview | null>(null);
  const [record, setRecord] = useState<LossRecord | null>(null);
  const [journal, setJournal] = useState<Journal>({ raw: null, attempt: null });
  const [reasons, setReasons] = useState<LossReason[]>(suppliedReasons ?? []);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [empty, setEmpty] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const locked = useRef(false);
  const lastFinalized = useRef<string | null>(null);
  const callbacks = useRef({ onFinalized, onPending });
  useEffect(() => { callbacks.current = { onFinalized, onPending }; }, [onFinalized, onPending]);

  async function load(token: number, completed = false) {
    const current = await fetchLossContext(dealId);
    if (epoch.current !== token) return;
    // Clear prior principal data before reading the new principal's journal.
    setCtx(current); setRecord(null); setPreview(null); setJournal({ raw: null, attempt: null });
    if (current.mapping_required) return;
    const scope = scopeOf(current);
    const saved = await readLossJournal(scope);
    const requestId = current.pending_request_id ?? current.latest_request_id;
    const active = requestId ? await fetchLossProgress(scope, requestId) : null;
    const nextPreview = !active ? await fetchLossPreview(scope) : null;
    let refreshed: LossContext;
    try { refreshed = await requireScope(scope); }
    catch (error) {
      if (epoch.current === token) { setCtx(null); setRecord(null); setPreview(null); setJournal({ raw: null, attempt: null }); }
      throw error;
    }
    if (epoch.current !== token) return;
    setCtx(refreshed); setJournal(saved); setRecord(active); setPreview(nextPreview);
    callbacks.current.onPending?.(active?.state === "pending" ? active.request_id : null);
    if (completed && active?.state === "finalized" && active.resolution
      && refreshed.stage === active.resolution.snapshot.to_stage && refreshed.latest_request_id === active.request_id
      && lastFinalized.current !== active.resolution.resolution_id) {
      lastFinalized.current = active.resolution.resolution_id;
      callbacks.current.onFinalized?.(active.resolution, active);
    }
  }
  useEffect(() => {
    const token = ++epoch.current;
    let alive = true;
    locked.current = true;
    void load(token).catch(e => { if (alive) setError(message(e)); }).finally(() => {
      if (alive) { locked.current = false; setBusy(false); }
    });
    if (!suppliedReasons) void fetchLossReasons().then(rows => { if (alive) setReasons(rows); });
    return () => { alive = false; epoch.current = token + 1; };
    // A new deal gets an entirely new operation epoch, including A -> B -> A.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function run(action: (token: number) => Promise<void>) {
    if (locked.current) return;
    const token = epoch.current;
    locked.current = true; setBusy(true); setError("");
    try { await action(token); }
    catch (e) {
      if (epoch.current === token) {
        setError(message(e));
        if (ctx && !ctx.mapping_required) {
          try { const saved = await readLossJournal(scopeOf(ctx)); if (epoch.current === token) setJournal(saved); }
          catch (storageError) { if (epoch.current === token) setError(message(storageError)); }
        }
      }
    } finally { if (epoch.current === token) { locked.current = false; setBusy(false); } }
  }
  function send(kind: LossAttempt["kind"]) {
    void run(async token => {
      if (!ctx) return;
      const scope = scopeOf(ctx);
      await requireScope(scope);
      if (epoch.current !== token) return;
      const requestKey = crypto.randomUUID();
      let body: RequestBody | ResolveBody;
      let requestId: string;
      if (kind === "request") {
        if (!preview || !reason.trim()) return;
        requestId = requestKey;
        body = { organization_id: scope.org, request_key: requestKey, expected_composition_digest: preview.composition_digest,
          reason_code: reason.trim(), comment: comment.trim() || null, finalize_if_empty: empty };
      } else {
        if (!record || !evidence.trim()) return;
        requestId = record.request_id;
        body = { request_key: requestKey, expected_request_digest: record.request_digest, evidence: evidence.trim() };
      }
      const next = await beginLossCommand(scope, kind, body, requestId, journal.raw);
      if (epoch.current !== token) return;
      setJournal(next);
      await dispatchLoss(next, true);
      if (epoch.current === token) await load(token, true);
    });
  }
  function retry() {
    void run(async token => { await dispatchLoss(journal); if (epoch.current === token) await load(token, true); });
  }
  function recover() {
    void run(async token => { await recoverLoss(journal); if (epoch.current === token) await load(token, true); });
  }
  function startNew() {
    void run(async token => {
      if (!ctx) return;
      const scope = scopeOf(ctx);
      const current = await requireScope(scope);
      if (current.pending_request_id) { await load(token); return; }
      const next = await fetchLossPreview(scope);
      if (epoch.current === token) { setRecord(null); setPreview(next); setReason(""); setComment(""); setEmpty(false); setEvidence(""); }
    });
  }
  const unresolved = !!journal.attempt && ["pending", "uncertain"].includes(journal.attempt.outcome);
  const frozen = record?.snapshot ?? preview?.snapshot;
  const rows = record?.invoices ?? preview?.invoices ?? [];
  const moneyLabels: Record<string, string> = { no_receipts: "Поступлений в проверенных данных нет", fully_refunded: "Полный возврат подтверждён",
    funds_held: "Деньги ещё не возвращены полностью", history_unknown: "Денежная история не установлена" };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
    <section role="dialog" aria-modal="true" aria-labelledby="deal-loss-title" className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-surface p-5 shadow-pop">
      <div className="flex items-center justify-between gap-3"><h2 id="deal-loss-title" className="text-lg font-semibold">Отказ сделки</h2>
        <button className={BUTTON} onClick={onCancel}>Закрыть окно</button></div>
      <p className="my-2 text-sm text-muted">{dealLabel}</p>
      {busy && <p role="status">Проверка и сохранение…</p>}
      {error && <p role="alert" className="my-3 text-red-700">{error}</p>}
      <button className={BUTTON} disabled={busy} onClick={() => void run(t => load(t))}>Обновить сведения</button>
      {ctx && <p className="my-3 text-sm">Учётная запись: {ctx.principal}. {ctx.organization
        ? `Юрлицо: ${ctx.organization.name} · ${ctx.organization.unp}.` : "Юрлицо сделки не подтверждено."}</p>}
      {ctx?.mapping_required && <p role="alert">Для отказа нужна подтверждённая принадлежность сделки юридическому лицу.
        Главный бухгалтер должен подтвердить её в разделе подготовки сделки при оформлении счёта.
        После подтверждения обновите сведения.</p>}
      {unresolved && <div className="my-4 rounded-lg border border-amber-400 p-3">
        <p>Результат исходной команды не установлен. UUID: {JSON.parse(journal.attempt!.body).request_key}.
          Новая команда не отправляется.</p>
        <div className="mt-2 flex flex-wrap gap-2"><button className={BUTTON} disabled={busy} onClick={recover}>Проверить результат команды</button>
          <button className={BUTTON} disabled={busy} onClick={retry}>Повторить исходную команду</button></div>
      </div>}
      {journal.attempt?.outcome === "rejected" && <p className="my-2 text-amber-800">Сервер отклонил команду. Перед новым подтверждением обновите сведения.</p>}
      {frozen && <div className="my-4"><p>Исходная стадия: {frozen.stage}. Счетов: {frozen.invoices.length}.</p>
        {frozen.invoices.length === 0 && <p>По подтверждённой принадлежности счетов нет.</p>}
        <ul className="mt-2 space-y-2">{frozen.invoices.map(invoice => {
          const r = rows.find(v => v.document_id === invoice.id);
          return <li key={invoice.id} className="rounded-lg border border-line p-3">
            <strong>Счёт ID {invoice.id} · версия {invoice.version}</strong>
            <p>Статус: {r?.status ? documentStatusLabels[r.status] ?? "Неизвестен — нужна сверка" : "Не проверен"}. Резерв: {r?.reserve_status ? reservationStatusLabels[r.reserve_status] ?? "Неизвестен — нужна сверка" : "Не проверен"}.</p>
            {r?.money && <p>{moneyLabels[r.money.state] ?? r.money.state}. Получено: {r.money.received}; возвращено: {r.money.refunded}.</p>}
            {r?.ready ? <p className="text-green-700">Отмена и освобождение резерва подтверждены.</p>
              : <p className="text-amber-800">Для закрытия требуется подтверждённая отмена главбухом; оплаченный счёт — только после полного возврата.
                Черновики и неизвестная история требуют сверки.</p>}
            {!!r?.blockers?.length && <div className="text-sm text-muted"><p>Что нужно сделать:</p><ul className="list-disc pl-5">{r.blockers.map((code, index) =>
              <li key={`${index}:${code}`}>{blockerLabels[code] ?? "Бухгалтеру нужно проверить основание блокировки в карточке счёта."}</li>)}</ul>
              {r.blockers.some(code => !blockerLabels[code]) && <details className="mt-1 text-xs"><summary>Диагностика для поддержки</summary><p>{r.blockers.filter(code => !blockerLabels[code]).join("; ")}</p></details>}
            </div>}
            {ctx?.organization_id && <a className="underline" href={`/crm/deals/${dealId}?org=${ctx.organization_id}&invoice=${invoice.id}#document-register`}>Открыть счёт и аннулирование</a>}
          </li>;
        })}</ul>
      </div>}
      {record && <div className="my-3 rounded-lg bg-sunken p-3"><p>Запрос {record.request_id}: {record.state === "pending" ? "ожидает завершения" : record.state === "finalized" ? "отказ завершён" : "отозван"}.</p>
        <p>Причина: {reasons.find(r => r.code === record.command.reason_code)?.title ?? record.command.reason_code}.
          {record.command.comment && ` Комментарий: ${record.command.comment}`}</p>
        <p className="text-xs">Автор запроса: {record.actor}. {record.resolution && `Квитанция: ${record.resolution.resolution_id}.`}</p>
      </div>}
      {ctx && !ctx.mapping_required && !record && preview && !unresolved && <div className="space-y-3">
        <label className="block">Причина отказа{reasons.length ? <select className={INPUT} aria-label="Причина отказа" value={reason} onChange={e => setReason(e.target.value)} disabled={busy}>
          <option value="">Выберите причину</option>{reasons.map(r => <option key={r.code} value={r.code}>{r.title}</option>)}</select>
          : <input className={INPUT} aria-label="Причина отказа" placeholder="Код причины отказа" maxLength={128} value={reason} onChange={e => setReason(e.target.value)} disabled={busy} />}</label>
        <textarea className={INPUT} aria-label="Комментарий к отказу" placeholder="Комментарий (необязательно)" maxLength={2000} value={comment} onChange={e => setComment(e.target.value)} disabled={busy} />
        {preview.snapshot.invoices.length === 0 && <label className="block"><input type="checkbox" checked={empty} onChange={e => setEmpty(e.target.checked)} disabled={busy} /> Закрыть сейчас, если счетов нет</label>}
        <button className={BUTTON} disabled={busy || !reason.trim() || !preview.snapshot.lost_stage} onClick={() => send("request")}>Запросить отказ</button>
      </div>}
      {record?.state === "pending" && !unresolved && <div className="space-y-3">
        <p>Сделка остаётся на исходной стадии до подтверждённого завершения отказа. Выпуск и отгрузка новых счетов приостановлены.</p>
        <textarea className={INPUT} aria-label="Основание завершения или отзыва" placeholder="Основание завершения или отзыва запроса" maxLength={2000} value={evidence} onChange={e => setEvidence(e.target.value)} disabled={busy} />
        <div className="flex flex-wrap gap-2"><button className={BUTTON} disabled={busy || !record.ready_to_finalize || !evidence.trim()} onClick={() => send("finalize")}>Завершить отказ</button>
          <button className={BUTTON} disabled={busy || !evidence.trim()} onClick={() => send("withdraw")}>Отозвать запрос</button></div>
        <p className="text-xs text-muted">Отзыв запроса не восстанавливает уже отменённые счета.</p>
      </div>}
      {record && record.state !== "pending" && !unresolved && ctx?.stage !== ctx?.lost_stage
        && <button className={BUTTON} disabled={busy} onClick={startNew}>Подготовить новый запрос</button>}
      <p className="mt-4 text-xs text-muted">Внешние сообщения не отправляются. Оплаты, возвраты и аннулирование счетов выполняются уполномоченными сотрудниками в соответствующих регистрах.</p>
    </section>
  </div>;
}
