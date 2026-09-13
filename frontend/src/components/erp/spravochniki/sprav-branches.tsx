"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { saveCounterpartyBranch, type CounterpartyBranch, type CounterpartyBranchWrite, type CounterpartyCard } from "@/lib/reference-data";

const modes = { unknown: "Не подтверждён", shared: "В составе головного предприятия", independent: "Самостоятельное исполнение налоговых обязательств" };
type Draft = CounterpartyBranchWrite["manual"];
type Editing = { id: number | null; revision?: number; parentRevision: number; draft: Draft; contacts: NonNullable<CounterpartyBranchWrite["contacts"]> };

export function SpravBranches({ card }: { card: CounterpartyCard }) {
  const router = useRouter();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [awaited, setAwaited] = useState<{ id: number; revision: number } | null>(null);
  const latch = useRef(false);
  const branches = card.branches ?? [];
  const awaitingRefresh = awaited !== null && !branches.some((b) => b.id === awaited.id && b.revision >= awaited.revision);
  const eligible = card.is_active && card.merged_into_id === null && !!card.legal_name?.trim() && /^[0-9]{9}$/.test(card.unp ?? "") && !!card.revision;

  function open(branch: CounterpartyBranch | null) {
    if (!eligible || awaitingRefresh) return;
    setMessage("");
    setEditing({ id: branch?.id ?? null, revision: branch?.revision, parentRevision: card.revision!,
      contacts: (branch?.contacts ?? []).map((c) => ({ ...c })),
      draft: branch ? { name: branch.name, address: branch.address, tax_mode: branch.tax_mode, portal_branch_code: branch.portal_branch_code, is_active: branch.is_active }
        : { name: "", address: null, tax_mode: "unknown", portal_branch_code: null, is_active: true } });
  }

  function change(patch: Partial<Draft>) {
    setEditing((current) => current ? { ...current, draft: { ...current.draft, ...patch } } : null);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!editing || latch.current) return;
    if (!editing.draft.name.trim()) { setMessage("Укажите название филиала"); return; }
    if (editing.draft.portal_branch_code !== null && !/^[0-9]{4}$/.test(editing.draft.portal_branch_code)) {
      setMessage("Код филиала должен содержать четыре цифры, включая ведущие нули"); return;
    }
    latch.current = true;
    setPending(true);
    setMessage("");
    const result = await saveCounterpartyBranch(card.id, editing.id, {
      expected_legal_entity_revision: editing.parentRevision,
      ...(editing.id === null ? {} : { expected_revision: editing.revision }),
      manual: { ...editing.draft, name: editing.draft.name.trim(), address: editing.draft.address?.trim() || null },
      contacts: editing.contacts,
    });
    if (result.status === "success") {
      setAwaited({ id: result.id, revision: result.revision });
      setEditing(null);
      setMessage("Филиал сохранён");
      router.refresh();
    } else {
      setMessage(result.message);
    }
    latch.current = false;
    setPending(false);
  }

  return <section className="rounded-2xl bg-surface p-5 shadow-card" aria-label="Головное предприятие и филиалы">
    <h2 className="font-semibold text-ink">Головное предприятие и филиалы</h2>
    <p className="mt-2 text-sm text-muted">Головное предприятие: <Link href={`/erp/spravochniki/counterparty/${card.id}`} className="text-accent hover:underline">{card.legal_name || card.display_name || card.name}</Link> · УНП {card.unp || "не заполнен"}</p>
    {branches.length === 0 && <p className="mt-3 text-sm text-muted">Филиалы не добавлены</p>}
    <div className="mt-3 space-y-3">{branches.map((branch) => <article id={`branch-${branch.id}`} key={branch.id} className="rounded-xl bg-sunken p-3">
      <h3 className="font-medium text-ink">Филиал: {branch.name}{!branch.is_active && " · В архиве"}</h3>
      <p className="text-sm text-muted">{branch.address || "Адрес не заполнен"}</p>
      <p className="text-sm text-muted">Налоговый режим: {modes[branch.tax_mode]}</p>
      <p className="text-sm text-muted">Код филиала для ЭСЧФ: {branch.portal_branch_code || "Не подтверждён"}</p>
      <div className="mt-2 text-sm">{(branch.contacts ?? []).map((c) => <p key={c.id}>Контакт филиала: {c.full_name}{c.is_primary && " · Основной"}{c.phone && ` · ${c.phone}`}{c.email && ` · ${c.email}`}</p>)}</div>
      <button type="button" disabled={!eligible || awaitingRefresh || editing !== null} onClick={() => open(branch)} className="mt-2 text-sm text-accent disabled:opacity-50">Редактировать филиал {branch.name}</button>
    </article>)}</div>
    {!eligible && <p className="mt-3 text-sm text-muted">Для добавления филиала заполните УНП и юридическое наименование активного головного предприятия.</p>}
    {awaitingRefresh && <p role="status" className="mt-3 text-sm text-muted">Ожидание обновления карточки…</p>}
    {message && <p role={editing ? "alert" : "status"} className="mt-3 text-sm">{message}</p>}
    {!editing ? <button type="button" disabled={!eligible || awaitingRefresh} onClick={() => open(null)} className="mt-3 rounded-lg border border-line px-3 py-2 text-sm disabled:opacity-50">Добавить филиал</button>
      : <form onSubmit={save} className="mt-4 space-y-3" aria-label="Редактор филиала">
        <fieldset disabled={pending} className="space-y-3">
          <label className="block text-sm">Название филиала<input aria-label="Название филиала" value={editing.draft.name} maxLength={255} onChange={(e) => change({ name: e.target.value })} className="mt-1 block w-full rounded-lg border border-line bg-surface p-2" /></label>
          <label className="block text-sm">Адрес филиала<input aria-label="Адрес филиала" value={editing.draft.address ?? ""} maxLength={1000} onChange={(e) => change({ address: e.target.value || null })} className="mt-1 block w-full rounded-lg border border-line bg-surface p-2" /></label>
          <label className="block text-sm">Налоговый режим филиала<select aria-label="Налоговый режим филиала" value={editing.draft.tax_mode} onChange={(e) => change({ tax_mode: e.target.value as Draft["tax_mode"] })} className="mt-1 block w-full rounded-lg border border-line bg-surface p-2">{Object.entries(modes).map(([value, title]) => <option key={value} value={value}>{title}</option>)}</select></label>
          <label className="block text-sm">Код филиала для ЭСЧФ<input aria-label="Код филиала для ЭСЧФ" inputMode="numeric" maxLength={4} value={editing.draft.portal_branch_code ?? ""} onChange={(e) => change({ portal_branch_code: e.target.value || null })} className="mt-1 block w-full rounded-lg border border-line bg-surface p-2" /></label>
          <p className="text-xs text-muted">Заполняйте код по справочнику портала ЭСЧФ. Если режим или код неизвестен, оставьте его неподтверждённым.</p>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={editing.draft.is_active} onChange={(e) => change({ is_active: e.target.checked })} />Филиал активен</label>
          <div className="space-y-3"><h3 className="font-medium">Контакты филиала</h3>{editing.contacts.map((contact, index) => <div key={contact.id ?? `new-${index}`} className="grid gap-2 rounded-lg border border-line p-3">
            {(["full_name", "phone", "email"] as const).map((field) => <label key={field} className="text-sm">{{ full_name: "Имя", phone: "Телефон", email: "Email" }[field]}<input aria-label={`Контакт филиала ${index + 1}: ${field}`} value={contact[field] ?? ""} onChange={(e) => setEditing((current) => current ? { ...current, contacts: current.contacts.map((c, i) => i === index ? { ...c, [field]: e.target.value || null } : c) } : null)} className="mt-1 block w-full rounded-lg border border-line bg-surface p-2" /></label>)}
            <label className="flex gap-2 text-sm"><input type="checkbox" aria-label={`Основной контакт филиала ${index + 1}`} checked={contact.is_primary ?? false} onChange={(e) => setEditing((current) => current ? { ...current, contacts: current.contacts.map((c, i) => ({ ...c, is_primary: i === index ? e.target.checked : false })) } : null)} />Основной контакт</label>
          </div>)}</div>
          <button type="button" disabled={editing.contacts.length >= 50} onClick={() => setEditing((current) => current ? { ...current, contacts: [...current.contacts, { full_name: "", phone: null, email: null, is_primary: false }] } : null)} className="text-sm text-accent">Добавить контакт филиала</button>
          <div className="flex gap-3"><button type="submit" className="rounded-lg bg-accent px-3 py-2 text-sm text-white">{pending ? "Сохранение…" : "Сохранить филиал"}</button><button type="button" onClick={() => { setEditing(null); setMessage(""); }} className="text-sm">Отмена</button></div>
        </fieldset>
      </form>}
  </section>;
}
