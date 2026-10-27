"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  loadCounterpartyRelationships,
  type CounterpartyRelationshipKind,
  type RelationshipPage,
} from "@/lib/counterparty-relationships";

const PAGE_SIZE = 20;
const sections: { kind: CounterpartyRelationshipKind; title: string }[] = [
  { kind: "contacts", title: "Контакты компании" },
  { kind: "deals", title: "Сделки CRM" },
  { kind: "calls", title: "Звонки" },
];

export function CounterpartyRelationships({ counterpartyId, focusContactId }: {
  counterpartyId: number;
  focusContactId?: number;
}) {
  return <section id="counterparty-relationships" className="space-y-4" aria-label="Связанные CRM записи">
    <h2 className="text-xl font-semibold text-ink">Связанные CRM записи</h2>
    <p className="text-sm text-muted">Показаны связи по точным ID. Контакты компании не означают участника каждой сделки или звонка.</p>
    <div className="grid gap-4 lg:grid-cols-2">
      {sections.map(({ kind, title }) => <RelationshipSection key={kind} kind={kind} title={title}
        counterpartyId={counterpartyId} focusContactId={kind === "contacts" ? focusContactId : undefined} />)}
    </div>
  </section>;
}

function RelationshipSection({ kind, title, counterpartyId, focusContactId }: {
  kind: CounterpartyRelationshipKind;
  title: string;
  counterpartyId: number;
  focusContactId?: number;
}) {
  const [offset, setOffset] = useState(0);
  const [requestedContactId, setRequestedContactId] = useState(focusContactId);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{ offset: number; revision: number; page?: RelationshipPage; error?: string } | null>(null);
  const state = loaded?.offset === offset && loaded.revision === revision ? loaded : null;

  useEffect(() => {
    const controller = new AbortController();
    void loadCounterpartyRelationships(counterpartyId, kind, offset, requestedContactId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setLoaded(result.status === "ok"
        ? { offset, revision, page: result.page }
        : { offset, revision, error: result.status === "forbidden" ? "Нет доступа к связанным записям."
          : result.status === "unauthorized" ? "Сессия истекла. Войдите в систему."
            : "Не удалось загрузить связанные записи." });
    });
    return () => controller.abort();
  }, [counterpartyId, kind, offset, requestedContactId, revision]);

  useEffect(() => {
    if (kind !== "contacts" || focusContactId == null || !state?.page || state.page.kind !== "contacts") return;
    if (!state.page.items.some((contact) => contact.id === focusContactId)) return;
    const node = document.getElementById(`counterparty-contact-${focusContactId}`);
    if (node && typeof node.scrollIntoView === "function") node.scrollIntoView({ block: "center" });
  }, [focusContactId, kind, state]);

  function retry() { setLoaded(null); setRevision((value) => value + 1); }
  function move(next: number) { setLoaded(null); setOffset(next); }
  const page = state?.page;

  return <section id={kind === "contacts" ? "counterparty-contacts" : undefined}
    className="space-y-3 rounded-2xl border border-line bg-surface p-4" aria-label={title}>
    <h3 className="font-semibold text-ink">{title}</h3>
    {!state && <p role="status" className="text-sm text-muted">Загрузка: {title.toLowerCase()}…</p>}
    {state?.error && <div role="alert" className="space-y-2 text-sm text-red-700">
      <p>{state.error}</p><button type="button" className="underline" onClick={retry}>Повторить</button>
    </div>}
    {page && page.kind === "contacts" && <>
      {page.items.length === 0 ? <p className="text-sm text-muted">{requestedContactId == null
        ? "Контакты компании не найдены." : "Контакт не найден для этой компании; ссылка не подтверждена."}</p> : <ul className="space-y-2">
        {page.items.map((contact) => <li id={`counterparty-contact-${contact.id}`} key={contact.id}
          className="rounded-lg bg-sunken px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center gap-2 font-medium text-ink">
            <span>{contact.full_name}</span>{contact.is_primary && <span className="text-xs text-muted">Основной</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted">
            <span>{contact.phone ?? "Телефон не указан"}</span><span>{contact.email ?? "Email не указан"}</span>
          </div>
        </li>)}
      </ul>}
      {requestedContactId != null && <button type="button" className="text-xs underline" onClick={() => {
        setRequestedContactId(undefined);
        setOffset(0);
      }}>Показать все контакты компании</button>}
    </>}
    {page && page.kind === "deals" && <>
      {page.items.length === 0 ? <p className="text-sm text-muted">Связанные сделки не найдены.</p> : <ul className="space-y-2">
        {page.items.map((deal) => <li key={deal.id} className="rounded-lg bg-sunken px-3 py-2 text-sm">
          <Link className="font-medium text-accent underline" href={`/crm/deals/${deal.id}`}>{deal.number} — {deal.title}</Link>
          <p className="mt-1 text-xs text-muted">Стадия: {deal.stage} · Ответственный: {managerLabel(deal.owner_id, deal.responsible_manager)}</p>
        </li>)}
      </ul>}
    </>}
    {page && page.kind === "calls" && <>
      {page.items.length === 0 ? <p className="text-sm text-muted">Связанные звонки не найдены.</p> : <ul className="space-y-2">
        {page.items.map((call) => <li key={call.id} className="rounded-lg bg-sunken px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-ink">{call.direction === "out" ? "Исходящий" : "Входящий"} · {call.status}</span>
            <span className="text-xs text-muted">{call.started_at.slice(0, 16).replace("T", " ")}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            <Link className="underline" href={`/crm/calls?counterparty_id=${counterpartyId}&call_id=${call.id}#call-${call.id}`}>Открыть звонок</Link>
            {call.crm_client_id != null && <Link className="underline" href={`/crm/clients/${call.crm_client_id}`}>Карточка CRM</Link>}
            {call.contact_id != null && <Link className="underline" href={`/erp/spravochniki/counterparty/${counterpartyId}?contact=${call.contact_id}#counterparty-contact-${call.contact_id}`}>Контакт компании</Link>}
            {call.deal_id != null && <Link className="underline" href={`/crm/deals/${call.deal_id}`}>Сделка</Link>}
          </div>
          {call.result && <p className="mt-1 text-xs text-muted">{call.result}</p>}
        </li>)}
      </ul>}
    </>}
    {page && <div className="flex items-center justify-between gap-2 border-t border-line pt-2 text-xs text-muted">
      <span>{page.total === 0 ? "0 записей" : `${offset + 1}–${Math.min(offset + page.items.length, page.total)} из ${page.total}`}</span>
      <div className="flex gap-2">
        <button type="button" className="underline disabled:opacity-40" disabled={offset === 0}
          onClick={() => move(Math.max(0, offset - PAGE_SIZE))}>Назад</button>
        <button type="button" className="underline disabled:opacity-40" disabled={offset + PAGE_SIZE >= page.total}
          onClick={() => move(offset + PAGE_SIZE)}>Далее</button>
      </div>
    </div>}
  </section>;
}

function managerLabel(ownerId: number | null, manager: { employee_id: number; name: string; active: boolean } | null): string {
  if (ownerId === null) return "Не назначен";
  if (!manager || manager.employee_id !== ownerId) return "Ответственный не сопоставлен";
  if (manager.name === `Сотрудник №${ownerId}`) return "Сотрудник не сопоставлен";
  return `${manager.name}${manager.active ? "" : " (неактивен)"}`;
}
