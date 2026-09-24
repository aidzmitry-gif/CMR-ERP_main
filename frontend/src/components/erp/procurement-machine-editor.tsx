"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { formatNumber } from "@/lib/format";
import { sendEdit, fetchOrder, fetchEditHistory, fetchProcurementSkus, fetchLandedPreview, fetchExpectedReservations, fetchDealDemandOrder, fetchPlan, identity, organizations, emptyLine, decimalInput, ReadFailure, MutationUnknown, type EditCommand, type Identity, type Organization, type MachineOrder, type OrderEditHistory, type ProcurementSkuOption, type ProcurementSkuOptions, type LandedPreview, type ExpectedOrder, type DealDemandOrder, type Plan, type NewLine } from "@/lib/procurement-machine";
import { allocateDealDemand, clearDealDemandAllocation, loadDealDemandAllocation, type DealDemandAllocationScope, type PendingDealDemandAllocation, DealDemandError } from "@/lib/procurement-deal-demand";
import { ProcurementCustomerDeadlines } from "./procurement-customer-deadlines";
import { ProcurementPurchaseChain } from "./procurement-purchase-chain";

import { editorJournal, type Attempt, type Scope } from "@/lib/procurement-editor-journal";
import { confirmDiscardUnsaved, useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

const STATUS: Record<string, string> = { draft: "Черновик", ordered: "Заказан", shipped: "Отгружен", customs: "Таможня", received: "Принят", cancelled: "Отменён" };
const CHANGE_LABELS: Record<string, string> = { freight_byn: "Фрахт, BYN", supplier: "Поставщик", supplier_id: "Поставщик из справочника", eta_date: "Дата прибытия", status: "Статус", plan: "План поставки" };
const changeValue = (value: unknown) => value === null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
const message = (e: unknown) => e instanceof Error ? e.message : "Не удалось выполнить действие";
const validId = (s?: string) => s && /^[1-9]\d*$/.test(s) && Number(s) <= 2147483647 ? s : "";
const reserveUnits = (value: string) => { const [whole, fraction] = value.split("."); return BigInt(whole) * 100n + BigInt(fraction); };
const maxReserve = (left: string, right: string) => {
  const units = reserveUnits(left) < reserveUnits(right) ? reserveUnits(left) : reserveUnits(right);
  return `${units / 100n}.${String(units % 100n).padStart(2, "0")}`;
};
export function ProcurementMachineEditor({ orderId, suggestedOrg }: { orderId: number; suggestedOrg?: string }) {
  const [companies, setCompanies] = useState<Organization[]>([]); const [org, setOrg] = useState(validId(suggestedOrg)); const [error, setError] = useState(""); const [pending, setPending] = useState(false);
  useEffect(() => { let live = true; organizations().then(v => { if (live) setCompanies(v); }).catch(e => { if (live) setError(message(e)); }); return () => { live = false; }; }, []);
  return <main className="w-full space-y-4 overflow-auto p-6"><label>Юрлицо заказа<select className="ml-2 rounded border p-2" value={org} onChange={e => { if (confirmDiscardUnsaved(pending)) setOrg(e.target.value); }}><option value="">Выберите юрлицо</option>{companies.map(x => <option key={x.id} value={x.id}>{x.name} · {x.unp}</option>)}</select></label>{error && <p role="alert">{error}</p>}{org && <Editor key={`${org}/${orderId}`} org={Number(org)} orderId={orderId} onPendingChange={setPending} />}</main>;
}
function Editor({ org, orderId, onPendingChange }: { org: number; orderId: number; onPendingChange: (pending: boolean) => void }) {
  const router = useRouter();
  const [scope, setScope] = useState<Identity | null>(null); const [order, setOrder] = useState<MachineOrder | null>(null); const [preview, setPreview] = useState<LandedPreview | null>(null); const [expected, setExpected] = useState<ExpectedOrder | null>(null); const [demandOrder, setDemandOrder] = useState<DealDemandOrder | null>(null); const [plan, setPlan] = useState<Plan | null>(null);
  const [history, setHistory] = useState<OrderEditHistory | null>(null); const [historyError, setHistoryError] = useState(""); const [historyBusy, setHistoryBusy] = useState(false);
  const [skuSearch, setSkuSearch] = useState(""); const [skuOptions, setSkuOptions] = useState<ProcurementSkuOptions | null>(null); const [selectedSku, setSelectedSku] = useState<ProcurementSkuOption | null>(null); const [skuError, setSkuError] = useState("");
  const [draft, setDraft] = useState<NewLine>(emptyLine()); const [freight, setFreight] = useState(""); const [status, setStatus] = useState("ordered"); const [statusTouched, setStatusTouched] = useState(false); const [method, setMethod] = useState("truck"); const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(true); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [attempt, setAttempt] = useState<Attempt | null>(null); const [legacy, setLegacy] = useState(false); const [prepared, setPrepared] = useState(false); const [unknownNotice, setUnknownNotice] = useState(false); const [allocationRecovery, setAllocationRecovery] = useState<PendingDealDemandAllocation | null>(null);
  const generation = useRef(0); const locked = useRef(false); const principal = useRef<string | null>(null); const stored = useRef<Attempt | null>(null);
  const journalKey = `procurement-editor/${org}/${orderId}`;
  const active = (n: number) => generation.current === n;
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      void fetchProcurementSkus(org, skuSearch).then((value) => { if (live) { setSkuOptions(value); setSkuError(""); } })
        .catch((cause) => { if (live) { setSkuOptions(null); setSkuError(message(cause)); } });
    }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [org, skuSearch]);
  function clearView() { setOrder(null); setPreview(null); setExpected(null); setDemandOrder(null); setPlan(null); setHistory(null); setScope(null); }
  async function who(n: number, expected?: string) {
    let current: Identity;
    try { current = await identity(org); } catch (e) { if (active(n)) clearView(); throw e; }
    if (!active(n)) throw new Error("Контекст изменился");
    if (expected && current.principal !== expected) { clearView(); throw new Error("Пользователь изменился. Откройте заказ заново."); }
    return current;
  }
  async function load(n: number, current: Identity) {
    let complete = true;
    const result = await fetchOrder(org, orderId);
    const confirmed = await who(n, current.principal);
    if (!active(n)) return;
    setScope(confirmed); setOrder(result);
    if (!freightDirty) setFreight(result.freight_byn);
    // A missing estimate is not a zero cost and must not hide the editable order.
    try { const v = await fetchLandedPreview(org, orderId); await who(n, current.principal); if (active(n)) setPreview(v); }
    catch (e) { complete = false; if (active(n)) { setPreview(null); setError(message(e)); if (e instanceof ReadFailure && [401, 403].includes(e.status)) { clearView(); throw e; } } }
    try { const v = await fetchExpectedReservations(org, orderId); await who(n, current.principal); if (active(n)) setExpected(v); }
    catch { if (active(n)) setExpected(null); }
    try { const v = await fetchDealDemandOrder(org, orderId); await who(n, current.principal); if (active(n)) setDemandOrder(v); }
    catch { if (active(n)) setDemandOrder(null); }
    try { const v = await fetchPlan(org, orderId); await who(n, current.principal); if (active(n)) { setPlan(v); if (!planDirty) { setMethod(v.transport_method_code ?? "truck"); setTarget(v.target_arrival_date ?? ""); } } }
    catch (e) { complete = false; if (active(n)) { setPlan(null); setError(message(e)); if (e instanceof ReadFailure && [401, 403].includes(e.status)) { clearView(); throw e; } } }
    try { const v = await fetchEditHistory(org, orderId); await who(n, current.principal); if (active(n)) { setHistory(v); setHistoryError(""); } }
    catch (e) { complete = false; if (active(n)) { setHistory(null); setHistoryError(message(e)); if (e instanceof ReadFailure && [401, 403].includes(e.status)) { clearView(); throw e; } } }
    return complete;
  }
  useEffect(() => {
    const n = ++generation.current;
    async function start() {
      try {
        const current = await who(n); principal.current = current.principal;
        const saved = sessionStorage.getItem(journalKey);
        if (saved) { setLegacy(true); setNotice("Старая попытка без UUID остаётся неразрешённой. Она не будет автоматически отправлена заново; требуется проверка перехода со старой версии."); }
        await syncJournal(n, current);
        await load(n, current);
      } catch (e) { if (active(n)) { clearView(); setError(message(e)); } }
      finally { if (active(n)) setBusy(false); }
    }
    void start(); return () => { generation.current = n + 1; };
    // One mounted editor owns one organization/order. No async result crosses its generation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [org, orderId]);
  async function syncJournal(n: number, current: Identity) {
    const saved = await editorJournal.load({ ...current, order_id: orderId });
    await who(n, current.principal);
    if (active(n)) { stored.current = saved; setAttempt(saved); setUnknownNotice(saved?.state === "pending"); }
    return saved;
  }
  async function deliver(n: number, current: Identity, saved: Attempt) {
    await who(n, current.principal);
    if (!active(n)) return;
    const result = await sendEdit(current, JSON.parse(saved.body), saved.mode);
    await who(n, current.principal);
    if (!active(n)) return;
    const terminal = await editorJournal.settle({ ...current, order_id: orderId }, saved, result);
    if (!active(n)) return;
    stored.current = terminal; setAttempt(terminal); setPrepared(false); setUnknownNotice(false);
    setNotice(result.outcome === "applied" ? "Изменение сохранено. Серверная квитанция подтверждена." : `Команда завершена без изменения заказа: ${result.code}.`);
    if (result.outcome === "applied" && JSON.parse(saved.body).action === "add_line") { setDraft(emptyLine()); setSelectedSku(null); }
    try { await load(n, current); }
    catch (e) { if (active(n)) { setOrder(null); setPreview(null); setDemandOrder(null); setPlan(null); setError(`Квитанция сохранена, но состав не обновлён: ${message(e)}`); } return false; }
    return result.outcome === "applied";
  }
  async function perform(action: EditCommand["action"], payload: Record<string, unknown>) {
    if (locked.current || busy || uncertain || !scope || needsPreparation) return false;
    locked.current = true; setBusy(true); setError(""); setNotice(""); const n = generation.current;
    try {
      const current = await who(n, principal.current ?? undefined);
      if (!current.can_manage) { setScope(current); throw new Error("Для изменения заказа нужны права главного бухгалтера"); }
      if (sessionStorage.getItem(journalKey)) { setLegacy(true); throw new Error("Старая попытка без UUID требует отдельной проверки"); }
      const claimed = await editorJournal.claim({ ...current, order_id: orderId }, stored.current, action, payload);
      if (!active(n)) return false;
      stored.current = claimed.attempt; setAttempt(claimed.attempt);
      if (!claimed.created) { setNotice("Другая вкладка уже сохранила попытку. Восстановите её с тем же UUID."); return false; }
      return await deliver(n, current, claimed.attempt);
    } catch (e) { if (active(n)) { if (e instanceof MutationUnknown || stored.current?.state === "pending") setUnknownNotice(true); setError(message(e)); } }
    finally { if (active(n)) { locked.current = false; setBusy(false); } }
    return false;
  }
  async function recover(reconcile: boolean) {
    if (locked.current || busy || legacy || !scope) return;
    locked.current = true; setBusy(true); setError(""); const n = generation.current;
    try {
      const current = await who(n, principal.current ?? undefined);
      if (!current.can_manage) { setScope(current); throw new Error("Для восстановления нужны права главного бухгалтера"); }
      const s: Scope = { ...current, order_id: orderId };
      let pending = await syncJournal(n, current);
      if (!pending || pending.state !== "pending") return;
      if (reconcile) pending = await editorJournal.reconcile(s, pending);
      if (!active(n)) return;
      stored.current = pending; setAttempt(pending);
      await deliver(n, current, pending);
    } catch (e) { if (active(n)) { if (stored.current?.state === "pending") setUnknownNotice(true); setError(message(e)); } }
    finally { if (active(n)) { locked.current = false; setBusy(false); } }
  }
  async function refreshReview() {
    if (locked.current) return; locked.current = true; setBusy(true); setError(""); const n = generation.current;
    try { const current = await who(n, principal.current ?? undefined); await syncJournal(n, current); await load(n, current); }
    catch (e) { if (active(n)) { clearView(); setError(message(e)); } }
    finally { if (active(n)) { locked.current = false; setBusy(false); } }
  }
  async function moreHistory() {
    if (historyBusy || !history?.next_after_id || !scope) return;
    const n = generation.current; const after = history.next_after_id;
    setHistoryBusy(true); setHistoryError("");
    try {
      const current = await who(n, principal.current ?? undefined);
      const next = await fetchEditHistory(org, orderId, after);
      await who(n, current.principal);
      if (active(n)) setHistory((previous) => previous?.next_after_id === after
        ? { ...next, items: [...previous.items, ...next.items] } : previous);
    } catch (e) { if (active(n)) setHistoryError(message(e)); }
    finally { if (active(n)) setHistoryBusy(false); }
  }
  const uncertain = legacy || attempt?.state === "pending";
  const needsPreparation = attempt?.state === "settled" && attempt.result?.outcome === "rejected" && !prepared;
  const readonly = busy || uncertain || needsPreparation || !scope?.can_manage || !order || ["received", "cancelled"].includes(order.status);
  const noCommand = busy || uncertain || needsPreparation || !scope?.can_manage || !order;
  const draftDirty = JSON.stringify(draft) !== JSON.stringify(emptyLine());
  const freightDirty = !!order && freight !== order.freight_byn;
  const planDirty = plan ? method !== (plan.transport_method_code ?? "truck") || target !== (plan.target_arrival_date ?? "") : method !== "truck" || target !== "";
  const unsaved = draftDirty || freightDirty || planDirty || statusTouched;
  useUnsavedDocumentGuard(unsaved || uncertain, onPendingChange);
  const unit = new Map(preview?.lines.map(x => [x.sku_code, x.unit_landed_cost_byn]));
  function add() {
    try { if (!selectedSku || draft.sku_code !== selectedSku.code) throw new Error("Выберите номенклатуру из справочника"); const line = { sku_code: selectedSku.code, sku_id: selectedSku.id, sku_title: selectedSku.title, sku_unit: selectedSku.unit, qty: decimalInput(draft.qty, 2, true), goods_value_byn: decimalInput(draft.goods_value_byn, 2), weight: decimalInput(draft.weight, 3), volume: decimalInput(draft.volume, 4) }; void perform("add_line", line); } catch (e) { setError(message(e)); }
  }
  function saveFreight() {
    if (readonly || !order) return;
    try { const value = decimalInput(freight, 2); if (value !== decimalInput(order.freight_byn, 2)) void perform("header", { freight_byn: value }); }
    catch { setError("Фрахт должен быть неотрицательным точным числом с двумя знаками"); setFreight(order.freight_byn); }
  }
  async function saveStatus() {
    if (await perform("status", { status })) setStatusTouched(false);
  }
  async function saveAndClose() {
    if (locked.current || busy || uncertain || needsPreparation || !scope || !order) return;
    const changes: Record<string, Record<string, unknown>> = {};
    try {
      if (draftDirty) {
        if (!selectedSku || draft.sku_code !== selectedSku.code) throw new Error("Выберите номенклатуру из справочника для новой позиции.");
        changes.add_line = { sku_code: selectedSku.code, sku_id: selectedSku.id, sku_title: selectedSku.title, sku_unit: selectedSku.unit, qty: decimalInput(draft.qty, 2, true), goods_value_byn: decimalInput(draft.goods_value_byn, 2), weight: decimalInput(draft.weight, 3), volume: decimalInput(draft.volume, 4) };
      }
      if (freightDirty) changes.header = { freight_byn: decimalInput(freight, 2) };
      if (planDirty) {
        if (!target) throw new Error("Укажите дату «В Минске до» для изменённого плана.");
        changes.plan = { transport_method_code: method, target_arrival_date: target };
      }
      if (statusTouched && status !== order.status) changes.status = { status };
    } catch (cause) { setError(message(cause)); return; }
    if (Object.keys(changes).length && !await perform("save", changes)) return;
    router.push(`/erp/procurement/orders?org=${org}`);
  }
  async function allocate(lineId: number, candidate: DealDemandOrder["lines"][number]["candidates"][number], freeForClient: string) {
    if (locked.current || busy || uncertain || needsPreparation || !scope?.can_manage || !order || ["received", "cancelled"].includes(order.status)) return;
    let qty: string;
    try { qty = maxReserve(candidate.free_qty, freeForClient); if (qty === "0.00") throw new Error("Свободного количества для распределения нет"); }
    catch (e) { setError(message(e)); return; }
    locked.current = true; setBusy(true); setError(""); setNotice(""); setUnknownNotice(false); const n = generation.current;
    try {
      const current = await who(n, principal.current ?? undefined);
      if (!current.can_manage) { setScope(current); throw new Error("Для распределения резерва нужны права главного бухгалтера"); }
      const allocationScope: DealDemandAllocationScope = { organization_id: org, principal: current.principal, order_id: orderId };
      const result = await allocateDealDemand(allocationScope, candidate, lineId, qty);
      if (!active(n)) return;
      setAllocationRecovery(null);
      setNotice(`Предварительный резерв ${qty} по ${candidate.sku_code} распределён на сделку №${candidate.deal_id}.`);
      await load(n, current);
      if (result.replayed) setNotice(`Подтверждён ранее созданный предварительный резерв ${qty} по сделке №${candidate.deal_id}.`);
    } catch (e) {
      if (active(n)) {
        setError(message(e));
        if (e instanceof DealDemandError) {
          try { setAllocationRecovery(loadDealDemandAllocation({ organization_id: org, principal: principal.current ?? "", order_id: orderId }, candidate.demand_id, lineId)); }
          catch { setAllocationRecovery(null); }
        }
      }
    } finally { if (active(n)) { locked.current = false; setBusy(false); } }
  }
  function closeAllocationAttempt() {
    if (!allocationRecovery) return;
    try { clearDealDemandAllocation(allocationRecovery); setAllocationRecovery(null); setNotice("Сохранённая команда распределения закрыта без изменения заказа."); }
    catch (e) { setError(message(e)); }
  }
  return <section className="space-y-4" aria-label="Редактор заказа">
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <button disabled={busy} onClick={() => void refreshReview()}>Проверить состав</button>
    <button disabled={busy || uncertain || needsPreparation || !order} onClick={() => void saveAndClose()}>Сохранить и закрыть</button>
    {uncertain && unknownNotice && <p role="status">Исход команды не подтверждён сервером. Обновление состава не разрешает повторную запись.</p>}
    {!legacy && attempt?.state === "pending" && <div><p>UUID: {JSON.parse(attempt.body).request_key}</p><button disabled={busy || !scope?.can_manage} onClick={() => void recover(false)}>Повторить сохранённую команду</button><button disabled={busy || !scope?.can_manage} onClick={() => void recover(true)}>Сверить и закрыть неисполненную</button></div>}
    {attempt?.state === "settled" && <p>Квитанция: {attempt.result?.outcome === "applied" ? "выполнено" : "отказ без изменения заказа"}. Это результат сохранённой команды, а не текущее состояние заказа.</p>}
    {allocationRecovery && <div role="status"><p>Сохранённая команда распределения резерва требует повторной проверки. Повторите кнопку у той же сделки или закройте команду после сверки.</p><button disabled={busy} onClick={closeAllocationAttempt}>Закрыть сохранённую команду</button></div>}
    {needsPreparation && <button disabled={busy || legacy} onClick={() => { setPrepared(true); setNotice("Проверьте данные и явно отправьте новую команду."); }}>Подготовить новую попытку</button>}
    {busy && <p>Проверяем данные…</p>}
    {order && <><h1 className="text-xl font-semibold">Состав заказа {order.number}</h1><p>{order.supplier || "Поставщик не указан"} · {STATUS[order.status]} {order.eta_date && `· ETA ${order.eta_date}`}</p>
      {!scope?.can_manage && <p>Доступен просмотр. Для изменений нужны права главного бухгалтера.</p>}
      {["received", "cancelled"].includes(order.status) && <p>Состав принятого или отменённого заказа не редактируется.</p>}
      <label>Фрахт партии, BYN<input className="ml-2 rounded border p-2" inputMode="decimal" value={freight} onChange={e => setFreight(e.target.value)} disabled={readonly} /></label><button disabled={readonly || !freightDirty} onClick={saveFreight}>Сохранить фрахт</button>
      <p className="rounded border border-amber-400 p-2 text-sm">Предварительный резерв относится к ожидаемой поставке: товар ещё не на складе и физический остаток или резерв не изменяются.</p>
      <table className="w-full text-left"><thead><tr>{["Номенклатура", "Кол-во", "Предварительный резерв", "Товар, BYN", "Вес, кг", "Объём, м³", "Себест/шт", ""].map((s, i) => <th key={i}>{s}</th>)}</tr></thead><tbody>
        {!order.lines.length && <tr><td colSpan={8}>Позиций нет — добавьте первую ниже.</td></tr>}
        {order.lines.map(line => { const r = expected?.lines.find(x => x.order_line_id === line.id); const d = demandOrder?.lines.find(x => x.order_line_id === line.id); return <tr key={line.id}><td>{line.sku_code}</td><td>{line.qty}</td><td>{r ? <div aria-label={`Предварительный резерв ${line.sku_code}`}><div title={`Заказано ${r.ordered}; принято ${r.accepted}`}>Ожидается {r.expected} · клиентам {r.expected_reserved} · свободно {r.free_expected}</div><div className="text-[11px] text-faint">по накладным {r.accepted} · принято складом {r.warehouse_accepted} · уже переведено {r.converted} · доступно после приёмки {r.physical_convertible} · ожидают сверки {r.pending_conversion_count}</div></div> : "Прогноз предварительного резерва недоступен"}{d && <div className="text-[11px] text-faint">под заказ клиентам {d.client_ordered} · свободно для клиента {d.free_for_client}{r && ` · свободно ожидается ${r.free_expected}`}</div>}{d?.candidates.length ? <div className="mt-1 space-y-1 text-[11px]"><span className="block">Свободные потребности:</span>{d.candidates.map(candidate => { const available = r ? maxReserve(d.free_for_client, r.free_expected) : d.free_for_client; const qty = maxReserve(candidate.free_qty, available); const target = candidate.document_id === null ? `сделка №${candidate.deal_id} · счёт не указан` : `сделка №${candidate.deal_id} · счёт ID ${candidate.document_id}`; return <div key={candidate.demand_id} className="flex flex-wrap items-center gap-1"><span>{target}: {candidate.free_qty} шт.</span><button disabled={noCommand || ["received", "cancelled"].includes(order.status) || qty === "0.00"} onClick={() => void allocate(line.id, candidate, qty)}>Закрепить ожидаемые {qty}</button></div>; })}</div> : null}</td><td>{line.goods_value_byn}</td><td>{line.weight}</td><td>{line.volume}</td><td>{unit.has(line.sku_code) ? formatNumber(Number(unit.get(line.sku_code))) : "—"}</td><td><button aria-label="Удалить позицию" disabled={readonly} onClick={() => void perform("delete_line", { line_id: line.id })}>Удалить</button></td></tr>; })}
      </tbody></table>
      {preview && <p>Итого landed: {preview.total_landed_byn} BYN</p>}
      <fieldset disabled={readonly} className="flex flex-wrap gap-2"><legend>Новая позиция</legend><label>Поиск номенклатуры<input className="block rounded border p-2" value={skuSearch} onChange={e => setSkuSearch(e.target.value)} /></label><label>Номенклатура из справочника<select aria-label="Номенклатура из справочника" className="block rounded border p-2" value={selectedSku?.id ?? ""} onChange={e => { const row = skuOptions?.items.find(item => String(item.id) === e.target.value) ?? null; setSelectedSku(row); setDraft(current => ({ ...current, sku_code: row?.code ?? "" })); }}><option value="">Выберите товар</option>{selectedSku && !skuOptions?.items.some(item => item.id === selectedSku.id) && <option value={selectedSku.id}>{selectedSku.code} · {selectedSku.title} · {selectedSku.unit}</option>}{skuOptions?.items.map(item => <option key={item.id} value={item.id}>{item.code} · {item.title} · {item.unit}</option>)}</select></label>{skuOptions?.truncated && <p>Показаны первые 50 товаров. Уточните поиск.</p>}{skuError && <p role="alert">Справочник недоступен: {skuError}</p>}{([['qty', 'Количество'], ['goods_value_byn', 'Стоимость товара'], ['weight', 'Вес'], ['volume', 'Объём']] as const).map(([key, label]) => <label key={key}>{label}<input className="block rounded border p-2" value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}<button onClick={add}>Добавить позицию</button></fieldset>
      <fieldset disabled={noCommand || ["received", "cancelled"].includes(order.status)}><legend>Статус машины</legend><label>Новый статус<select value={status} onChange={e => { setStatus(e.target.value); setStatusTouched(true); }}>{Object.entries(STATUS).filter(([s]) => s !== "draft").map(([s, label]) => <option key={s} value={s}>{label}</option>)}</select></label><button onClick={() => void saveStatus()}>Изменить статус</button></fieldset>
      <fieldset disabled={noCommand}><legend>План машины</legend><label>Способ перевозки<select value={method} onChange={e => setMethod(e.target.value)}><option value="truck">Машина</option><option value="container">Контейнер</option></select></label><label>В Минске до<input type="date" value={target} onChange={e => setTarget(e.target.value)} /></label><button onClick={() => { if (!target) { setError("Укажите дату «В Минске до»"); return; } void perform("plan", { transport_method_code: method, target_arrival_date: target }); }}>Пересчитать план</button></fieldset>
      <p>Клиентские сроки и штрафы не проверены.</p><ProcurementCustomerDeadlines key={`${org}:${orderId}:${JSON.stringify(plan)}:${JSON.stringify(expected)}`} org={org} orderId={orderId} disabled={noCommand} onUseDate={setTarget} />{plan && <><p>Всего дней: {plan.total_days}. Начало: {plan.start_date ?? "не задано"}</p>{plan.schedule_start_in_past && <p>Дата начала собственного графика уже прошла.</p>}{plan.milestones.map(x => <p key={x.stage}>{x.title}: план {x.planned_date ?? "—"}, факт {x.actual_date ?? "—"}</p>)}</>}
      <ProcurementPurchaseChain org={org} orderId={orderId} />
      <section aria-label="История изменений заказа" className="space-y-2 rounded border border-line p-3">
        <h2 className="font-semibold">История изменений · {order.number}</h2>
        {historyError && <p role="alert">История недоступна: {historyError}</p>}
        {history && history.items.length === 0 && <p>Изменений пока нет.</p>}
        {history?.items.map((item) => <article key={item.id} className="border-t border-line pt-2 text-sm">
          <p>№ {item.id} · {item.changed_at} · {item.changed_by}</p>
          {item.changes.map((change, index) => <p key={`${change.field}/${index}`}>
            {CHANGE_LABELS[change.field] ?? change.field}: {change.before_unknown ? "прежнее значение не сохранено" : changeValue(change.before)} → {changeValue(change.after)}
          </p>)}
        </article>)}
        {history?.next_after_id !== null && history && <button disabled={historyBusy} onClick={() => void moreHistory()}>Ещё изменения</button>}
      </section>
    </>}
  </section>;
}
