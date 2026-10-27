"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { confirmMoneyHistory, fetchMoneyReview, moneyId, moneyReviewKey, MoneyReconciliationError, validMoneyConfirmation, type MoneyConfirmation, type MoneyReceipt, type MoneyReview } from "@/lib/invoice-money-reconciliation-api";

type Props = { org: string; document: string; disabled?: boolean; revision?: number; acquire: () => boolean; release: () => void; onBusyChange: (busy: boolean) => void };
const states = { no_receipts: "Поступлений в проверяемых данных нет. Это не доказывает отсутствия исторических оплат.", funds_held: "Полученные средства возвращены не полностью.", fully_refunded: "По проверяемым данным поступления полностью возвращены.", history_unknown: "Денежная история требует сверки: полнота не установлена." };
const blockers: Record<string, string> = { funds_not_fully_refunded: "Средства возвращены не полностью", future_money_history_requires_review: "Обнаружены денежные факты будущей даты", legacy_paid_without_receipts: "Исторический статус оплаты без подтверждённых поступлений", known_bank_unallocated: "Есть нераспределённая банковская операция", bank_basis_changed: "Основание банковской операции изменилось", bank_evidence_invalid: "Банковское основание требует проверки", cancelled_invoice_money_review_required: "Денежная история отменённого счёта требует проверки" };
const empty = { source_key: "", history_from: "", history_through: "", evidence: "", references: "", checked: false };

export function AccountingInvoiceMoneyReconciliation(props: Props) { return <MoneySelection key={`${props.org}/${props.document}`} {...props} />; }
function MoneySelection(props: Props) {
  const [open, setOpen] = useState(false);
  return open ? <MoneyCard {...props} /> : <Button variant="secondary" disabled={props.disabled || !moneyId(props.org) || !moneyId(props.document)} onClick={() => setOpen(true)}>Открыть сверку денежной истории</Button>;
}
function MoneyCard({ org, document, disabled = false, revision = 0, acquire, release, onBusyChange }: Props) {
  const [review, setReview] = useState<MoneyReview | null>(null);
  const [form, setForm] = useState(empty);
  const [prepared, setPrepared] = useState<MoneyConfirmation | null>(null);
  const [saved, setSaved] = useState<MoneyReceipt | null>(null);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const mounted = useRef(false), inFlight = useRef(false), reading = useRef(false), generation = useRef(0), frozen = useRef<MoneyConfirmation | null>(null);
  const controls = useRef({ acquire, release, onBusyChange, disabled });
  useLayoutEffect(() => { controls.current = { acquire, release, onBusyChange, disabled }; }, [acquire, release, onBusyChange, disabled]);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; controls.current.release(); controls.current.onBusyChange(false); }; }, []);
  const refresh = useCallback(async () => {
    if (!moneyId(org) || !moneyId(document) || frozen.current || inFlight.current || reading.current || controls.current.disabled) return;
    const token = ++generation.current; reading.current = true; setLoading(true); setError(""); setReview(null); setForm((f) => ({ ...f, checked: false }));
    try {
      const value = await fetchMoneyReview(org, document);
      if (mounted.current && generation.current === token) { setReview(value); setForm((f) => ({ ...f, history_from: value.required_history_from, history_through: value.required_history_through, checked: false })); }
    } catch (e) { if (mounted.current && token === generation.current) setError((e as Error).message); }
    finally { if (mounted.current && token === generation.current) { reading.current = false; setLoading(false); } }
  }, [org, document]);
  useEffect(() => {
    let active = true;
    // A new allocation/revision invalidates an older read, without discarding
    // a frozen POST whose result may still be unknown.
    if (!inFlight.current && !frozen.current) { generation.current += 1; reading.current = false; }
    void Promise.resolve().then(() => { if (active) void refresh(); });
    return () => { active = false; };
  }, [refresh, revision, disabled]);
  useEffect(() => {
    const focus = () => { void refresh(); };
    const visible = () => { if (globalThis.document.visibilityState === "visible") void refresh(); };
    window.addEventListener("focus", focus); globalThis.document.addEventListener("visibilitychange", visible);
    return () => { window.removeEventListener("focus", focus); globalThis.document.removeEventListener("visibilitychange", visible); };
  }, [refresh]);
  const body: MoneyConfirmation = { source_key: form.source_key.trim(), expected_basis_digest: review?.basis_digest || "", history_from: form.history_from, history_through: form.history_through, evidence: form.evidence.trim(), source_references: form.references.split(/\r?\n/).map((s) => s.trim()), all_money_sources_checked: form.checked };
  async function confirm() {
    if (inFlight.current || reading.current || controls.current.disabled || saved || (!prepared && (!review || !validMoneyConfirmation(body, review))) || !controls.current.acquire()) return;
    inFlight.current = true; controls.current.onBusyChange(true); setBusy(true); setError(""); setNotice("");
    const token = ++generation.current, retry = !!frozen.current;
    let keepLocked = false;
    try {
      if (!retry) {
        const current = await fetchMoneyReview(org, document);
        if (!mounted.current || token !== generation.current) return;
        if (!review || moneyReviewKey(current) !== moneyReviewKey(review)) {
          setReview(current); setForm((f) => ({ ...f, history_from: current.required_history_from, history_through: current.required_history_through, checked: false }));
          setNotice("Факты или серверный день изменились. Проверьте новый просмотр и заново подтвердите полноту источников."); return;
        }
        frozen.current = body; setPrepared(body);
      }
      const payload = frozen.current!;
      keepLocked = true;
      const receipt = await confirmMoneyHistory(org, document, payload);
      if (!mounted.current || token !== generation.current) return;
      keepLocked = false; frozen.current = null; setPrepared(null); setSaved(receipt); setReview(null);
      setNotice(`Сверка № ${receipt.id} сохранена. Проверяем актуальность отдельно.`);
      try {
        const current = await fetchMoneyReview(org, document);
        if (mounted.current && token === generation.current) { setReview(current); setNotice(`Сверка № ${receipt.id} сохранена. Актуальность — по серверной проверке ${current.review_date}.`); }
      } catch (e) { if (mounted.current && token === generation.current) setError(`Запись сохранена, актуальность не проверена. ${(e as Error).message}`); }
    } catch (e) {
      if (mounted.current && token === generation.current) {
        setError((e as Error).message);
        if (!retry && e instanceof MoneyReconciliationError && [401, 403, 404, 409, 422].includes(e.status || 0)) { keepLocked = false; frozen.current = null; setPrepared(null); setReview(null); setForm((f) => ({ ...f, checked: false })); }
      }
    } finally {
      inFlight.current = false;
      if (mounted.current && token === generation.current) {
        setBusy(false);
        if (!keepLocked) { controls.current.release(); controls.current.onBusyChange(false); }
      }
    }
  }
  function newReview() { setSaved(null); setNotice(""); setForm(empty); void refresh(); }
  return <section aria-label="Сверка денежной истории счёта" className="space-y-3 rounded-xl border border-line p-4">
    <h3 className="font-semibold">Сверка денежной истории счёта</h3>
    <p>Юрлицо ID {org} · счёт ID {document}</p>
    <p className="text-sm text-muted">Подтверждение главного бухгалтера фиксирует проверку банка, кассы и исторических источников. Оно не разрешает отмену счёта: исполнение и отгрузки проверяются отдельно.</p>
    {!moneyId(org) || !moneyId(document) ? <p role="alert">Некорректный ID юрлица или счёта.</p> : <>
      <Button variant="secondary" disabled={disabled || busy || loading || !!prepared} onClick={() => void refresh()}>Обновить сверку</Button>
      {loading && <p role="status">Загрузка сверки…</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {review && <>
        <p>Серверная дата проверки: {review.review_date}</p><p>{states[review.money_state]}</p>
        <p>Требуемая история: {review.required_history_from} — {review.required_history_through}</p>
        {review.blockers.map((code) => <p key={code}>Требуется проверка: {blockers[code] || code}</p>)}
        <details><summary>Идентификатор просмотренных фактов</summary><p className="break-all">{review.basis_digest}</p></details>
        <p className="text-xs text-muted">Последние {review.records.length} записей (не более 20). Актуальность указана на момент серверной проверки.</p>
        {review.records.map((r) => <article aria-label={`Сверка ${r.id}`} key={r.id} className="rounded-lg border border-line p-3 text-sm">
          <p>Сверка № {r.id} · {r.current ? "Актуальна на момент серверной проверки" : "Требуется новая сверка"}</p>
          <p>{r.history_from} — {r.history_through} · {r.actor} · {r.created_at}</p><p>Основание: {r.evidence}</p>
          {r.source_references.map((s) => <p key={s}>Документальное основание: {s}</p>)}
        </article>)}
        {!saved && <fieldset disabled={disabled || busy || !!prepared || !review.can_confirm_money_history} className="grid gap-3 md:grid-cols-2">
          <label>Ключ сверки<Input aria-label="Ключ сверки" maxLength={160} value={form.source_key} onChange={(e) => setForm({ ...form, source_key: e.target.value })} /></label>
          <label>История с<Input aria-label="История с" type="date" value={form.history_from} onChange={(e) => setForm({ ...form, history_from: e.target.value })} /></label>
          <label>История по<Input aria-label="История по" type="date" value={form.history_through} onChange={(e) => setForm({ ...form, history_through: e.target.value })} /></label>
          <label>Основание сверки<Input aria-label="Основание сверки" maxLength={2000} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} /></label>
          <label className="md:col-span-2">Документальные ссылки, по одной на строке<textarea aria-label="Документальные ссылки" className="block w-full rounded border p-2" value={form.references} onChange={(e) => setForm({ ...form, references: e.target.value })} /></label>
          <label className="md:col-span-2"><input aria-label="Все денежные источники проверены" type="checkbox" checked={form.checked} onChange={(e) => setForm({ ...form, checked: e.target.checked })} /> Проверены все денежные источники за указанный период: банк, касса и исторические данные.</label>
        </fieldset>}
      </>}
      {prepared && <p>Результат отправки неизвестен. Поля и переходы зафиксированы; повтор использует тот же ключ и факты. Новый запрос пока недоступен.</p>}
      {!saved && <Button disabled={disabled || busy || loading || (!prepared && (!review || !validMoneyConfirmation(body, review)))} onClick={() => void confirm()}>{busy ? "Проверка и подтверждение сверки…" : prepared ? "Повторить сверку с тем же ключом" : "Подтвердить денежную историю"}</Button>}
      {saved && <Button variant="secondary" disabled={busy || disabled || loading} onClick={newReview}>Новая сверка</Button>}
    </>}
  </section>;
}
