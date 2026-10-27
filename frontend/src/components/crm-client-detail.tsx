"use client";

import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { DealContacts } from "@/components/deal-contacts";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { callLinkDeal, createDeal, fetchCallsResult, type CallRow } from "@/lib/api";
import { responsibleManagerText, validResponsibleManager, type ResponsibleManager } from "@/lib/crm-directory";

type Client = { id: number; name: string; owner_id: number; unp: string | null; source: "crm"; counterparty_id?: number | null; responsible_manager?: ResponsibleManager | null };
type LinkedDeal = { id: number; number: string; title: string };
type ClientDocument = { id: number; deal_id: number; deal_number: string; number: string; kind: string; version: number; original_state: string };

function ClientCallHistory({ counterpartyId, deals }: { counterpartyId: number | null | undefined; deals: LinkedDeal[] }) {
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{ counterpartyId: number; revision: number; rows?: CallRow[]; error?: string } | null>(null);
  const [selected, setSelected] = useState<Record<number, string>>({});
  const [savingCallIds, setSavingCallIds] = useState<number[]>([]);
  const [failedCallIds, setFailedCallIds] = useState<number[]>([]);
  const state = loaded && counterpartyId != null && loaded.counterpartyId === counterpartyId && loaded.revision === revision ? loaded : null;

  useEffect(() => {
    if (counterpartyId == null) return;
    let current = true;
    const controller = new AbortController();
    void fetchCallsResult({ counterparty_id: counterpartyId }, controller.signal).then((result) => {
      if (!current) return;
      if (!result.ok) {
        setLoaded({ counterpartyId, revision, error: result.error });
      } else if (result.rows.some((call) => call.counterparty_id !== counterpartyId)) {
        setLoaded({ counterpartyId, revision, error: "Сервер вернул звонки другого клиента." });
      } else {
        setLoaded({ counterpartyId, revision, rows: result.rows });
      }
    });
    return () => { current = false; controller.abort(); };
  }, [counterpartyId, revision]);

  async function linkCall(callId: number) {
    const dealId = Number(selected[callId]);
    if (savingCallIds.includes(callId) || !Number.isSafeInteger(dealId) || !deals.some((deal) => deal.id === dealId)) return;
    setSavingCallIds((ids) => [...ids, callId]);
    setFailedCallIds((ids) => ids.filter((id) => id !== callId));
    const linked = await callLinkDeal(callId, { deal_id: dealId });
    setSavingCallIds((ids) => ids.filter((id) => id !== callId));
    if (!linked) {
      setFailedCallIds((ids) => [...ids, callId]);
      return;
    }
    setFailedCallIds((ids) => ids.filter((id) => id !== callId));
    setSelected((values) => { const next = { ...values }; delete next[callId]; return next; });
    setRevision((value) => value + 1);
  }

  return <section className="space-y-3 rounded-xl border border-line p-4" aria-label="История звонков клиента">
    <div className="flex items-center justify-between gap-2">
      <h2 className="font-semibold">История звонков</h2>
      {counterpartyId != null && <button type="button" className="text-sm underline" onClick={() => setRevision((value) => value + 1)}>Обновить звонки</button>}
    </div>
    {counterpartyId == null && <p className="text-sm text-muted">История звонков появится после привязки клиента к контрагенту.</p>}
    {counterpartyId != null && !state && <p role="status">Загрузка звонков клиента…</p>}
    {state?.error && <p role="alert">{state.error} <button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Повторить</button></p>}
    {state?.rows?.length === 0 && <p className="text-sm text-muted">Звонков у клиента пока нет.</p>}
    {!!state?.rows?.length && <ul className="space-y-3">{state.rows.map((call) => {
      const linkedDeal = deals.find((deal) => deal.id === call.deal_id);
      const isUnlinked = call.deal_id === null;
      return <li key={call.id} className="space-y-2 border-t border-line pt-3 text-sm first:border-0 first:pt-0">
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <span>{call.started_at.slice(0, 16).replace("T", " ")}</span>
          <span>{call.direction === "out" ? "Исходящий" : "Входящий"}</span>
          <span>{call.phone_e164 ?? "—"}</span>
          <span>{call.result || call.status}</span>
          {linkedDeal ? <Link className="underline" href={`/crm/deals/${linkedDeal.id}`}>Сделка {linkedDeal.number}</Link>
            : call.deal_id != null ? <span className="text-muted">Сделка привязана</span>
              : !isUnlinked ? <span className="text-muted">Привязка сделки не указана</span> : null}
        </div>
        {isUnlinked && (deals.length > 0 ? <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={`Сделка для звонка ${call.id}`}
            className="max-w-full rounded border border-line bg-surface px-2 py-1"
            value={selected[call.id] ?? ""}
            onChange={(event) => setSelected((values) => ({ ...values, [call.id]: event.target.value }))}
          >
            <option value="">Выберите сделку</option>
            {deals.map((deal) => <option key={deal.id} value={deal.id}>{deal.number} — {deal.title}</option>)}
          </select>
          <button
            type="button"
            className="rounded bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-50"
            disabled={!selected[call.id] || savingCallIds.includes(call.id)}
            onClick={() => void linkCall(call.id)}
          >
            {savingCallIds.includes(call.id) ? "Привязка…" : `Привязать звонок ${call.id} к сделке`}
          </button>
          {failedCallIds.includes(call.id) && <span role="alert">Не удалось привязать звонок. Повторите попытку.</span>}
        </div> : <p className="text-muted">У клиента нет доступных сделок для привязки.</p>)}
      </li>;
    })}</ul>}
  </section>;
}

function ClientDocuments({ clientId }: { clientId: number }) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{ revision: number; rows?: ClientDocument[]; error?: string } | null>(null);
  const currentState = state?.revision === revision ? state : null;
  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/sales/clients/${clientId}/documents`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("load_failed");
        const rows = await response.json();
        if (!Array.isArray(rows) || !rows.every((row) => row && [row.id, row.deal_id, row.version].every((id) => Number.isSafeInteger(id) && id > 0)
          && [row.deal_number, row.number, row.kind, row.original_state].every((value) => typeof value === "string"))) throw new Error("malformed_response");
        if (current) setState({ revision, rows });
      } catch {
        if (current) setState({ revision, error: "Не удалось загрузить документы клиента." });
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [clientId, revision]);
  return <section className="space-y-3 rounded-xl border border-line p-4" aria-label="Документы клиента">
    <h2 className="font-semibold">Документы клиента</h2>
    <button type="button" className="text-sm underline" onClick={() => setRevision((value) => value + 1)}>Обновить документы</button>
    {!currentState && <p role="status">Загрузка документов…</p>}
    {currentState?.error && <p role="alert">{currentState.error} Нажмите «Обновить документы».</p>}
    {currentState?.rows?.length === 0 && <p className="text-sm text-muted">Документов пока нет.</p>}
    {!!currentState?.rows?.length && <ul className="space-y-2">{currentState.rows.map((document) => <li key={document.id} className="flex flex-wrap gap-2 text-sm">
      <span>{document.number} · версия {document.version}</span>
      <Link className="underline" href={`/crm/deals/${document.deal_id}`}>Сделка {document.deal_number}</Link>
      {document.original_state === "issued" ? <a className="underline" href={`/api/sales/documents/${document.id}/render`} target="_blank" rel="noreferrer">Оригинал {document.number}</a> : <span className="text-muted">Оригинал недоступен</span>}
    </li>)}</ul>}
  </section>;
}

export function CrmClientDetail({ clientId, focusContactId }: { clientId: number; focusContactId?: number }) {
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const generation = useRef(0);
  useLayoutEffect(() => () => { generation.current += 1; }, [clientId]);
  const [loaded, setLoaded] = useState<{ clientId: number; revision: number; client?: Client; deals?: LinkedDeal[]; error?: string } | null>(null);
  const state = loaded?.clientId === clientId && loaded.revision === revision ? loaded : null;
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    void (async () => {
      try {
        const responses = await Promise.all(["", "/deals"].map((suffix) => fetch(`/api/sales/clients/${clientId}${suffix}`, {
          cache: "no-store", signal: controller.signal,
        })));
        if (responses.some((response) => !response.ok)) throw new Error(responses.some((response) => response.status === 403 || response.status === 404)
          ? "Клиент недоступен." : "Не удалось загрузить клиента. Повторите попытку.");
        const [client, deals] = await Promise.all(responses.map((response) => response.json()));
        if (client?.id !== clientId || client.source !== "crm" || typeof client.name !== "string"
          || (client.unp !== null && typeof client.unp !== "string")
          || !Number.isSafeInteger(client.owner_id) || client.owner_id <= 0
          || (client.responsible_manager !== undefined && !validResponsibleManager(client.responsible_manager))
          || (client.counterparty_id !== undefined && client.counterparty_id !== null
            && (!Number.isSafeInteger(client.counterparty_id) || client.counterparty_id <= 0))
          || !Array.isArray(deals) || !deals.every((deal) => deal && Number.isSafeInteger(deal.id) && deal.id > 0 && typeof deal.number === "string" && typeof deal.title === "string")) {
          throw new Error("Сервер вернул некорректные данные клиента.");
        }
        if (current) setLoaded({ clientId, revision, client, deals });
      } catch (error) {
        if (current) setLoaded({ clientId, revision, error: error instanceof Error ? error.message : "Ошибка загрузки клиента." });
      }
    })();
    return () => { current = false; controller.abort(); };
  }, [clientId, revision]);

  return <section className="space-y-4 p-4 md:p-6" aria-label="Карточка клиента">
    <Link href="/crm/clients" className="text-sm underline">К списку клиентов</Link>
    {!state && <p role="status">Загрузка клиента…</p>}
    {state?.error && <div role="alert"><p>{state.error}</p><button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Повторить</button></div>}
    {state?.client && <>
      <h1 className="text-xl font-semibold">{state.client.name}</h1>
      <p className="text-sm text-muted">УНП: {state.client.unp ?? "Не указан"}</p>
      <p>Ответственный менеджер: {responsibleManagerText(state.client.responsible_manager)}</p>
      <DealContacts key={`contacts:${clientId}`} clientId={clientId} focusContactId={focusContactId} />
      <ClientCallHistory key={`calls:${clientId}:${state.client.counterparty_id ?? "none"}`} counterpartyId={state.client.counterparty_id} deals={state.deals ?? []} />
      <ClientDocuments key={`documents:${clientId}`} clientId={clientId} />
      <div className="space-y-3 rounded-xl border border-line p-4">
        <h2 className="font-semibold">Сделки клиента</h2>
        <button type="button" className="rounded-lg bg-accent px-4 py-2 text-white" onClick={() => { generation.current += 1; setCreating(true); }}>Новая сделка клиента</button>
        {state.deals?.length ? <ul className="space-y-2">{state.deals.map((deal) => <li key={deal.id}>
          <Link className="underline" href={`/crm/deals/${deal.id}`}>{deal.number} — {deal.title}</Link>
        </li>)}</ul> : <p className="text-sm text-muted">Сделок пока нет.</p>}
      </div>
      {creating && <CreateDealModal key={`deal:${clientId}`} client={state.client} stages={[]} defaultStage="new" onClose={() => { generation.current += 1; setCreating(false); }} onCreate={async (input) => {
        const operation = ++generation.current;
        const deal = await createDeal(input);
        if (operation !== generation.current) return false;
        if (!deal) return false;
        setCreating(false);
        setRevision((value) => value + 1);
        return true;
      }} />}
    </>}
  </section>;
}
