"use client";

import { useEffect, useRef, useState } from "react";

import { fetchProcurementSuppliers, identity, organizations,
  type Identity, type Organization, type ProcurementSupplierOption } from "@/lib/procurement-machine";
import { claimStatusLabel } from "@/lib/procurement-claims";
import { claimHistory, createClaim, listClaims, resolveClaim, searchClaimOrders,
  type ClaimCommand, type ClaimHistory, type ClaimOrder, type ClaimResolution,
  type OwnedClaim } from "@/lib/procurement-scoped-claims";

const inputClass = "rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink";
const newKey = () => crypto.randomUUID();

function emptyCommand(): ClaimCommand {
  return { claim_key: newKey(), supplier_id: 0, supplier: "", supplier_unp: "",
    order_id: null, item: "", reason: "", claim_type: "брак", qty_affected: 1,
    amount_byn: null, ownership_evidence: "" };
}

export function ProcurementScopedClaims() {
  const [companies, setCompanies] = useState<Organization[]>([]);
  const [companyError, setCompanyError] = useState("");
  const [org, setOrg] = useState("");
  const selected = useRef("");
  const [access, setAccess] = useState<Identity | null>(null);
  const [rows, setRows] = useState<OwnedClaim[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<ClaimCommand | null>(null);
  const [supplierSearch, setSupplierSearch] = useState("");
  const [suppliers, setSuppliers] = useState<ProcurementSupplierOption[]>([]);
  const [orderSearch, setOrderSearch] = useState("");
  const [orders, setOrders] = useState<ClaimOrder[]>([]);
  const [resolution, setResolution] = useState<(ClaimResolution & { claimId: number }) | null>(null);
  const [history, setHistory] = useState<ClaimHistory | null>(null);

  useEffect(() => {
    let live = true;
    void organizations().then(value => { if (live) setCompanies(value); })
      .catch(() => { if (live) setCompanyError("Не удалось загрузить юрлица"); });
    return () => { live = false; };
  }, []);

  async function chooseOrganization(value: string) {
    selected.current = value;
    setOrg(value); setAccess(null); setRows([]); setNext(null); setForm(null);
    setResolution(null); setHistory(null); setError(""); setSuppliers([]); setOrders([]);
    if (!value) return;
    setLoading(true);
    try {
      const [scope, page] = await Promise.all([identity(Number(value)), listClaims(Number(value))]);
      if (selected.current !== value) return;
      if (scope.organization_id !== Number(value)) throw new Error("Юрлицо доступа не совпало");
      setAccess(scope); setRows(page.items); setNext(page.next_after_id);
    } catch (cause) {
      if (selected.current === value) setError(String(cause));
    } finally {
      if (selected.current === value) setLoading(false);
    }
  }

  async function refresh() {
    if (!org) return;
    const value = org;
    const page = await listClaims(Number(value));
    if (selected.current === value) { setRows(page.items); setNext(page.next_after_id); }
  }

  async function findSuppliers() {
    if (!org || !supplierSearch.trim()) return;
    const value = org;
    try {
      const result = await fetchProcurementSuppliers(Number(value), supplierSearch);
      if (selected.current === value) setSuppliers(result.items);
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
  }

  async function findOrders() {
    if (!org) return;
    const value = org;
    try {
      const result = await searchClaimOrders(Number(value), orderSearch);
      if (selected.current === value) setOrders(result);
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
  }

  async function saveClaim() {
    if (!form || !access || !org) return;
    const value = org;
    setBusy(true); setError("");
    try {
      await createClaim(Number(value), access.principal, form);
      if (selected.current !== value) return;
      setForm(null); await refresh();
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
    finally { if (selected.current === value) setBusy(false); }
  }

  async function saveResolution() {
    if (!resolution || !access || !org) return;
    const value = org;
    setBusy(true); setError("");
    try {
      await resolveClaim(Number(value), resolution.claimId, access.principal, resolution);
      if (selected.current !== value) return;
      setResolution(null); await refresh();
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
    finally { if (selected.current === value) setBusy(false); }
  }

  async function openHistory(claimId: number) {
    if (!org) return;
    const value = org;
    setError("");
    try {
      const result = await claimHistory(Number(value), claimId);
      if (selected.current === value) setHistory(result);
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
  }

  async function loadMore() {
    if (!org || next === null) return;
    const value = org;
    setLoading(true);
    try {
      const page = await listClaims(Number(value), next);
      if (selected.current === value) { setRows(old => [...old, ...page.items]); setNext(page.next_after_id); }
    } catch (cause) { if (selected.current === value) setError(String(cause)); }
    finally { if (selected.current === value) setLoading(false); }
  }

  return <div className="flex-1 space-y-4 overflow-auto p-6">
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-sm">Юрлицо <select aria-label="Юрлицо претензий" className={inputClass}
        value={org} onChange={event => void chooseOrganization(event.target.value)}>
        <option value="">Выберите юрлицо</option>
        {companies.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}
      </select></label>
      {org && <span className="text-sm text-muted">Загружено претензий: {rows.length}</span>}
      {access?.can_manage && <button type="button" className="rounded-lg bg-accent px-3 py-2 text-sm text-white"
        onClick={() => { setForm(emptyCommand()); setError(""); }}>Новая претензия</button>}
    </div>
    {companyError && <p role="alert" className="text-red-700">{companyError}</p>}
    <p className="text-sm text-amber-700">Автоматические и старые претензии без подтверждённого юрлица здесь не показаны; их требуется отдельно сопоставить по первичным документам.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {loading && <p role="status">Загрузка…</p>}

    {form && access?.can_manage && <section aria-label="Новая претензия" className="space-y-3 rounded-xl border border-line bg-surface p-4">
      <h2 className="font-semibold">Новая претензия</h2>
      <div className="flex gap-2"><input aria-label="Поиск поставщика" className={inputClass} value={supplierSearch}
        onChange={event => { setSupplierSearch(event.target.value); setSuppliers([]);
          setForm({ ...form, supplier_id: 0, supplier: "", supplier_unp: "" }); }} />
        <button type="button" onClick={() => void findSuppliers()}>Найти в справочнике</button></div>
      <label className="block text-sm">Поставщик из справочника <select aria-label="Поставщик претензии" className={inputClass}
        value={form.supplier_id || ""} onChange={event => {
          const item = suppliers.find(row => row.id === Number(event.target.value));
          if (item) setForm({ ...form, supplier_id: item.id, supplier: item.name, supplier_unp: item.unp });
        }}><option value="">Выберите поставщика</option>
        {suppliers.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unp} · ID {row.id}</option>)}
      </select></label>
      <div className="flex gap-2"><input aria-label="Поиск заказа" className={inputClass} value={orderSearch}
        onChange={event => { setOrderSearch(event.target.value); setOrders([]); setForm({ ...form, order_id: null }); }} />
        <button type="button" onClick={() => void findOrders()}>Найти заказ</button></div>
      <label className="block text-sm">Заказ поставщику (если связан) <select aria-label="Заказ претензии" className={inputClass}
        value={form.order_id ?? ""} onChange={event => setForm({ ...form, order_id: event.target.value ? Number(event.target.value) : null })}>
        <option value="">Без подтверждённого заказа</option>
        {orders.map(row => <option key={row.id} value={row.id}>{row.number} · {row.supplier}</option>)}
      </select></label>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm">Изделие<input className={inputClass} value={form.item} onChange={event => setForm({ ...form, item: event.target.value })} /></label>
        <label className="text-sm">Тип<input className={inputClass} value={form.claim_type} onChange={event => setForm({ ...form, claim_type: event.target.value })} /></label>
        <label className="text-sm">Количество<input type="number" min="0" className={inputClass} value={form.qty_affected}
          onChange={event => setForm({ ...form, qty_affected: Number(event.target.value) })} /></label>
        <label className="text-sm">Заявленная сумма BYN<input className={inputClass} value={form.amount_byn ?? ""}
          onChange={event => setForm({ ...form, amount_byn: event.target.value || null })} /></label>
      </div>
      <label className="block text-sm">Причина<input className={inputClass} value={form.reason} onChange={event => setForm({ ...form, reason: event.target.value })} /></label>
      <label className="block text-sm">Основание принадлежности юрлицу<input className={inputClass} value={form.ownership_evidence}
        onChange={event => setForm({ ...form, ownership_evidence: event.target.value })} /></label>
      <div className="flex gap-3"><button type="button" className="rounded-lg bg-accent px-3 py-2 text-white" disabled={busy || !form.supplier_id || !form.item.trim() || !form.reason.trim() || !form.ownership_evidence.trim()}
        onClick={() => void saveClaim()}>{busy ? "Сохранение…" : "Сохранить и закрыть"}</button>
        <button type="button" disabled={busy} onClick={() => setForm(null)}>Отмена</button></div>
      <p className="text-xs text-muted">При сетевой ошибке форма и ключ операции сохраняются для точного повтора. Заявленная сумма не означает поступление денег.</p>
    </section>}

    {org && <div className="overflow-hidden rounded-xl border border-line bg-surface"><table className="w-full text-sm">
      <thead><tr className="border-b border-line text-left"><th className="p-3">№</th><th className="p-3">Поставщик</th>
        <th className="p-3">Изделие</th><th className="p-3">Заказ</th><th className="p-3">Статус</th><th className="p-3">Действия</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.claim.id} className="border-b border-line">
        <td className="p-3">{row.claim.id}</td><td className="p-3">{row.claim.supplier}</td>
        <td className="p-3">{row.claim.item}</td><td className="p-3">{row.order_id
          ? <a className="text-accent underline" href={`/erp/procurement/orders/${row.order_id}`}>{row.claim.order_code}</a> : "—"}</td>
        <td className="p-3">{claimStatusLabel(row.claim.status)}</td><td className="space-x-2 p-3">
          <button type="button" className="text-accent underline" onClick={() => void openHistory(row.claim.id)}>История</button>
          {access?.can_manage && row.claim.status === "open" && <button type="button" className="text-accent underline"
            onClick={() => setResolution({ claimId: row.claim.id, edit_key: newKey(), expected_status: "open",
              status: "resolved", resolution: "" })}>Решить</button>}</td>
      </tr>)}</tbody></table>
      {rows.length === 0 && !loading && <p className="p-4 text-muted">Подтверждённых претензий этого юрлица пока нет.</p>}
    </div>}
    {next !== null && <button type="button" disabled={loading} onClick={() => void loadMore()}>Загрузить ещё</button>}

    {resolution && <section aria-label="Решение претензии" className="space-y-2 rounded-xl border border-line bg-surface p-4">
      <h2 className="font-semibold">Претензия №{resolution.claimId}</h2>
      <label className="block text-sm">Результат <select className={inputClass} value={resolution.status}
        onChange={event => setResolution({ ...resolution, status: event.target.value as ClaimResolution["status"] })}>
        <option value="resolved">Решена</option><option value="rejected">Отклонена</option>
      </select></label>
      <label className="block text-sm">Как урегулировано<textarea className={inputClass} value={resolution.resolution}
        onChange={event => setResolution({ ...resolution, resolution: event.target.value })} /></label>
      <div className="flex gap-3"><button type="button" disabled={busy || !resolution.resolution.trim()}
        onClick={() => void saveResolution()}>Сохранить и закрыть</button>
        <button type="button" disabled={busy} onClick={() => setResolution(null)}>Отмена</button></div>
      <p className="text-xs text-muted">Решение сохраняет историю; оно само по себе не создаёт платёж.</p>
    </section>}

    {history && <section aria-label="История претензии" className="rounded-xl border border-line bg-surface p-4 text-sm">
      <div className="flex justify-between"><h2 className="font-semibold">История претензии №{history.claim_id}</h2>
        <button type="button" onClick={() => setHistory(null)}>Закрыть</button></div>
      <p>Создал: {history.created.actor} · {history.created.created_at} · {history.created.evidence}</p>
      {history.edits.map((edit, index) => <p key={index}>{edit.created_at} · {edit.actor}: {edit.before.status} → {edit.after.status}; {edit.after.resolution}</p>)}
    </section>}
  </div>;
}
