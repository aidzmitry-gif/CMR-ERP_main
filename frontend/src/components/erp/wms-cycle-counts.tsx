"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createCyclePlan, type CyclePlan, fetchCyclePlans, runCyclePlan } from "@/lib/wms-cycle-count";
import { type InventoryOrganization } from "@/lib/wms-inventory";
import { dueState } from "@/lib/wms-warehouse";
import { emptySourceDraft, InventoryOrganizationSelect, InventorySourceFields, sourcePayload, sourceReady, useInventoryRequestScope } from "./wms-inventory-source";

interface Props { initial: CyclePlan[]; today: string; organizations: InventoryOrganization[]; initialOrganizationId: number | null }
export function WmsCycleCounts(props: Props) {
  return <CycleCountsBody key={JSON.stringify([props.initialOrganizationId, props.initial])} {...props} />;
}

function CycleCountsBody({ initial, today, organizations, initialOrganizationId }: Props) {
  const router = useRouter();
  const request = useInventoryRequestScope();
  const [organizationId, setOrganizationId] = useState(initialOrganizationId);
  const [plans, setPlans] = useState<CyclePlan[] | null>(initialOrganizationId === null ? null : initial);
  const [form, setForm] = useState({ warehouse: "", zone: "", cadence: "30" });
  const [source, setSource] = useState(emptySourceDraft);
  const [runTarget, setRunTarget] = useState<CyclePlan | null>(null);
  const [runSource, setRunSource] = useState(emptySourceDraft);
  const cadence = Number(form.cadence);
  const validForm = organizationId !== null && form.warehouse.trim() && Number.isSafeInteger(cadence) && cadence > 0 && sourceReady(source);
  async function changeOrganization(id: number | null) {
    const ticket = request.begin();
    setOrganizationId(id); setPlans(null); setSource(emptySourceDraft()); setRunTarget(null); setRunSource(emptySourceDraft());
    try { if (id !== null) { const rows = await fetchCyclePlans(id); if (request.current(ticket)) setPlans(rows); } }
    catch (error) { request.fail(ticket, error); }
    finally { request.finish(ticket); }
  }
  async function onAdd() {
    if (request.busy || !validForm || organizationId === null) return;
    const ticket = request.begin();
    try {
      const plan = await createCyclePlan({ organization_id: organizationId, warehouse: form.warehouse.trim(), zone: form.zone.trim() || null,
        cadence_days: cadence, next_due_date: today, ...sourcePayload(source) });
      if (request.current(ticket)) { setPlans((rows) => [...(rows ?? []), plan]); setSource(emptySourceDraft()); }
    } catch (error) { request.fail(ticket, error); }
    finally { request.finish(ticket); }
  }
  async function onRun() {
    if (request.busy || !runTarget || runTarget.organization_id !== organizationId || !sourceReady(runSource)) return;
    const ticket = request.begin();
    try { const doc = await runCyclePlan(runTarget.id, sourcePayload(runSource)); if (request.current(ticket)) router.push(`/erp/wms/inventory/${doc.id}`); }
    catch (error) {
      request.fail(ticket, error);
      if (request.current(ticket)) setRunSource((draft) => ({ ...draft, confirmed: false }));
    }
    finally { request.finish(ticket); }
  }
  function chooseRun(plan: CyclePlan) { setRunTarget(plan); setRunSource(emptySourceDraft()); request.setError(""); }
  return <div className="min-w-0 flex-1 overflow-auto p-6">
    <p className="mb-4 text-sm text-muted">Планы пересчёта физического журнала. Каждый запуск требует нового подтверждения полноты и основания.</p>
    <InventoryOrganizationSelect organizations={organizations} value={organizationId} onChange={changeOrganization} />
    <div className="mt-4 flex flex-wrap gap-3">
      <label className="text-sm">Склад <input aria-label="Склад" value={form.warehouse} onChange={(e) => { setForm({ ...form, warehouse: e.target.value }); setSource({ ...source, confirmed: false }); }} className="rounded-lg border border-line px-2 py-1" /></label>
      <label className="text-sm">Зона (справочно) <input aria-label="Зона" value={form.zone} onChange={(e) => setForm({ ...form, zone: e.target.value })} className="rounded-lg border border-line px-2 py-1" /></label>
      <label className="text-sm">Период, дней <input aria-label="Период, дней" type="number" min={1} step={1} value={form.cadence} onChange={(e) => setForm({ ...form, cadence: e.target.value })} className="w-24 rounded-lg border border-line px-2 py-1" /></label>
    </div>
    <InventorySourceFields draft={source} onChange={setSource} disabled={request.busy || organizationId === null} />
    <button onClick={onAdd} disabled={request.busy || !validForm} className="mt-3 rounded-lg bg-accent px-3 py-2 text-white disabled:opacity-60">Создать план</button>
    {request.error && <div role="alert" className="mt-3 text-sm text-red-600">{request.error}
      {organizationId !== null && <button className="ml-2 underline" onClick={() => changeOrganization(organizationId)}>Повторить загрузку списка</button>}
    </div>}
    {request.busy && <p role="status" className="mt-3 text-sm">Выполняется запрос…</p>}
    {runTarget && <section aria-label="Подтверждение запуска" className="mt-4 rounded-xl border border-line p-4">
      <h2 className="font-medium">Запустить пересчёт: {runTarget.warehouse} · юрлицо {runTarget.organization_id}</h2>
      <InventorySourceFields draft={runSource} onChange={setRunSource} disabled={request.busy} />
      <button onClick={onRun} disabled={request.busy || !sourceReady(runSource)} className="mt-3 rounded-lg bg-accent px-3 py-2 text-white disabled:opacity-60">Подтвердить и запустить</button>
      <button onClick={() => { setRunTarget(null); setRunSource(emptySourceDraft()); }} disabled={request.busy} className="ml-3 underline">Отмена</button>
    </section>}
    {organizationId === null ? <p className="mt-4 text-sm text-muted">Выберите юрлицо для просмотра планов.</p> : plans !== null &&
      <div className="mt-4 overflow-auto rounded-xl border border-line"><table className="w-full text-sm">
        <thead><tr>{["Склад", "Зона (справочно)", "Период", "Следующий", "Статус", "Источник и основание", "Действие"].map((label) => <th key={label} className="p-3 text-left">{label}</th>)}</tr></thead>
        <tbody>{plans.length === 0 && !request.error && <tr><td colSpan={7} className="p-4 text-muted">Планов пока нет</td></tr>}
          {plans.filter((plan) => plan.organization_id === organizationId).map((plan) => <tr key={plan.id} className="border-t border-line">
            <td className="p-3">{plan.warehouse}</td><td className="p-3">{plan.zone || "весь склад"}</td><td className="p-3">{plan.cadence_days} дн</td><td className="p-3">{plan.next_due_date || "—"}</td>
            <td className="p-3">{{ overdue: "Просрочено", today: "Сегодня", upcoming: "Предстоит", none: "—" }[dueState(plan.next_due_date, today)]}</td>
            <td className="p-3">{plan.expected_source === "wms_physical" ? "Физический журнал WMS" : "Источник не подтверждён"}<br />{plan.source_evidence || "Основание неизвестно"}<br />{plan.journal_confirmed_by || "Автор неизвестен"}<br />{plan.journal_confirmed_at || "Время неизвестно"}</td>
            <td className="p-3"><button onClick={() => chooseRun(plan)} disabled={request.busy || !plan.active || plan.expected_source !== "wms_physical"} className="rounded-lg border border-line px-2 py-1 disabled:opacity-60">Запустить</button></td>
          </tr>)}
        </tbody></table></div>}
  </div>;
}
