"use client";

import { useEffect, useRef, useState } from "react";
import { documentStatusLabels as states } from "@/lib/document-status-labels";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { fetchRegisterOrganizations, registerId, type RegisterOrganization } from "@/lib/document-register-api";
import { fetchClientDocument, fetchClientDocuments, fetchClientOriginal, type ClientDocument, type ClientDocumentPage } from "@/lib/client-document-register-api";
import { ShipmentDocumentDraft } from "@/components/erp/shipment-document-draft";

const kinds: Record<string, string> = { invoice: "Счёт", contract: "Договор", order: "Заказ" };

export function ClientDocumentRegister({ clientId }: { clientId: string }) {
  return <ClientSelection key={clientId} clientId={clientId} />;
}
function ClientSelection({ clientId }: { clientId: string }) {
  const [org, setOrg] = useState("");
  const [organizations, setOrganizations] = useState<RegisterOrganization[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!registerId(clientId)) return;
    let active = true;
    void fetchRegisterOrganizations().then((value) => { if (active) setOrganizations(value); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [clientId, attempt]);
  return <section aria-label="Документы клиента по юрлицу" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Документы клиента по юрлицу</h2>
    {!registerId(clientId) ? <p role="alert">Некорректный ID клиента.</p> : <>
      <p className="text-sm">Точный клиент MDM ID {clientId}. Включаются только сделки с подтверждённой принадлежностью этому ID.</p>
      <label className="block text-sm">Юрлицо документов клиента<Select aria-label="Юрлицо документов клиента" disabled={!organizations} value={org} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите юрлицо</option>{organizations?.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select></label>
      {!organizations && !error && <p role="status">Загрузка доступных юрлиц…</p>}
      {organizations?.length === 0 && <p>Нет доступных юрлиц.</p>}
      {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" onClick={() => { setError(""); setAttempt((n) => n + 1); }}>Повторить список юрлиц</Button></>}
      {registerId(org) && <ClientFilters key={org} org={org} clientId={clientId} />}
    </>}
  </section>;
}
function ClientFilters({ org, clientId }: { org: string; clientId: string }) {
  const [kind, setKind] = useState("");
  return <div className="space-y-3">
    <label className="block text-sm">Вид документов клиента<Select aria-label="Вид документов клиента" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Все виды</option>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Select></label>
    <ClientPage key={kind} org={org} clientId={clientId} kind={kind} />
    <p className="text-xs text-muted">Неподтверждённые сделки не включены. Совпадение названия и слияние MDM не переносят исторические документы между ID.</p>
  </div>;
}
function ClientPage({ org, clientId, kind }: { org: string; clientId: string; kind: string }) {
  const [page, setPage] = useState<ClientDocumentPage | null>(null);
  const [after, setAfter] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const paging = useRef(false);
  useEffect(() => {
    let active = true;
    void fetchClientDocuments(org, clientId, kind, after).then((value) => {
      if (active) setPage((previous) => after && previous ? { ...value, items: [...previous.items, ...value.items], shipment_documents: [...previous.shipment_documents, ...value.shipment_documents.filter((row) => !previous.shipment_documents.some((old) => old.act_id === row.act_id))] } : value);
    }).catch((e: Error) => { if (active) setError(e.message); })
      .finally(() => { if (active) { setBusy(false); paging.current = false; } });
    return () => { active = false; };
  }, [org, clientId, kind, after, attempt]);
  function next() { if (paging.current || busy || !page?.next_after_id) return; paging.current = true; setBusy(true); setError(""); setSelected(null); setAfter(page.next_after_id); }
  return <div className="space-y-3">
    {busy && <p role="status">Загрузка документов клиента…</p>}
    {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" disabled={busy} onClick={() => { setBusy(true); setError(""); setAttempt((n) => n + 1); }}>Повторить реестр клиента</Button></>}
    {page && <div className="rounded-lg border border-line p-3 text-sm">
      <p>Текущая запись MDM ID {page.client_current.id}: {page.client_current.name} · УНП {page.client_current.unp || "не указан"}</p>
      {!page.client_current.is_active && <p>Текущая запись неактивна. История ниже относится к исходному ID.</p>}
      {page.client_current.merged_into_id !== null && <p>В MDM указан преемник ID {page.client_current.merged_into_id}. Документы автоматически не перенесены.</p>}
    </div>}
    {page && <ClientShipmentDocuments page={page} org={org} />}
    {page?.items.length === 0 && !busy && !error && <p>В выбранном юрлице и доступном CRM-контексте подтверждённые документы клиента по фильтру не найдены.</p>}
    {page?.items.map((row) => <ClientRow key={row.id} row={row} onSelect={setSelected} />)}
    {page && page.next_after_id !== null && !error && <Button variant="secondary" disabled={busy} onClick={next}>Ещё документы клиента</Button>}
    {selected !== null && <ClientVersion key={selected} org={org} clientId={clientId} id={selected} onClose={() => setSelected(null)} onSelect={setSelected} />}
  </div>;
}

function ClientShipmentDocuments({ page, org }: { page: ClientDocumentPage; org: string }) {
  if (page.coverage.shipments === "unavailable") return <p className="text-xs text-muted">Реестр внутренних актов отгрузки недоступен. Это не означает отсутствия отгрузок.</p>;
  return <section aria-label="Внутренние акты отгрузки клиента" className="space-y-2 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">Внутренние акты отгрузки клиента</h3>
    <p className="text-xs text-muted">Акты WMS показаны по точной подтверждённой принадлежности клиента. Они не являются ТН или ТТН; из каждого акта можно подготовить проверяемый черновик реквизитов.</p>
    {page.shipment_documents.length === 0 ? <p>Подтверждённых внутренних актов по документам этой страницы нет.</p> : <ul className="space-y-1">{page.shipment_documents.map((row) => <li key={row.act_id}>
      <a className="text-accent underline" href={row.document_url} target="_blank" rel="noreferrer">Акт WMS № {row.act_id}</a>
      <span> · счёт ID {row.document_id} · дата {row.operation_date} · строк {row.line_count} · {row.actor}</span>
      <ShipmentDocumentDraft org={org} sourceKey={row.source_key} />
    </li>)}</ul>}
  </section>;
}
function ClientRow({ row, onSelect, detail = false }: { row: ClientDocument; onSelect: (id: number) => void; detail?: boolean }) {
  return <article aria-label={`Документ клиента ${row.id}`} className="space-y-1 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">{kinds[row.kind] || row.kind} · {row.number} · версия {row.version} · ID {row.id}</h3>
    <p className="tabular-nums">{row.amount} {row.currency || "Валюта неизвестна"} · {states[row.status] || row.status}</p>
    <p>Историческая принадлежность: клиент ID {row.client_snapshot.id} · {row.client_snapshot.name} · УНП {row.client_snapshot.unp || "не указан"}</p>
    <a className="text-accent underline" href={`/crm/deals/${row.deal_id}`}>Открыть сделку ID {row.deal_id}</a>
    {row.reserve_status === "consumed" && <p>Исторический статус резерва: требуется сверка.</p>}
    {row.original_state === "legacy_unavailable" && <p>Оригинал не сохранён. Историческое содержание неизвестно.</p>}
    {row.original_state === "draft" && <p>Черновик — не исторический оригинал.</p>}
    {row.original_state === "approval_copy" && <p>Сохранённая копия на согласовании — не выпущена.</p>}
    {row.replacement_reason && <p>Причина замены: {row.replacement_reason}</p>}
    <div className="flex flex-wrap gap-2">
      {!detail && <Button variant="secondary" onClick={() => onSelect(row.id)}>Открыть документ клиента ID {row.id}</Button>}
      {row.supersedes_id !== null && <Button variant="ghost" onClick={() => onSelect(row.supersedes_id!)}>Заменяет документ ID {row.supersedes_id}</Button>}
      {row.superseded_by_id !== null && <Button variant="ghost" onClick={() => onSelect(row.superseded_by_id!)}>Заменён документом ID {row.superseded_by_id}</Button>}
    </div>
  </article>;
}
function ClientVersion({ org, clientId, id, onClose, onSelect }: { org: string; clientId: string; id: number; onClose: () => void; onSelect: (id: number) => void }) {
  const [row, setRow] = useState<ClientDocument | null>(null);
  const [error, setError] = useState("");
  const [original, setOriginal] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void fetchClientDocument(org, clientId, id).then((value) => { if (active) setRow(value); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, clientId, id, attempt]);
  return <section aria-label="Выбранный документ клиента" className="space-y-3 rounded-xl border border-accent p-3">
    <Button variant="ghost" onClick={onClose}>Закрыть документ клиента</Button>
    {!row && !error && <p role="status">Проверка принадлежности документа…</p>}
    {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" onClick={() => { setError(""); setAttempt((n) => n + 1); }}>Повторить проверку документа</Button></>}
    {row && <><ClientRow row={row} onSelect={onSelect} detail />
      {row.original_available && <Button variant="secondary" onClick={() => setOriginal(true)}>{row.original_state === "approval_copy" ? "Сохранённая копия клиента" : "Оригинал клиента"} ID {row.id}</Button>}
      {original && <ClientOriginal org={org} clientId={clientId} id={id} onClose={() => setOriginal(false)} />}
    </>}
  </section>;
}
function ClientOriginal({ org, clientId, id, onClose }: { org: string; clientId: string; id: number; onClose: () => void }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void fetchClientOriginal(org, clientId, id).then((value) => { if (active) setHtml(value); })
      .catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, clientId, id]);
  return <div className="space-y-2">
    <Button variant="ghost" onClick={onClose}>Закрыть оригинал клиента</Button>
    {html === null && !error && <p role="status">Проверка сохранённого оригинала…</p>}
    {error && <p role="alert" className="text-red-700">{error} Предпросмотр не заменяет оригинал.</p>}
    {html !== null && <iframe title={`Оригинал клиента ${clientId} документ ${id}`} sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="h-[32rem] w-full rounded-lg border border-line bg-white" />}
  </div>;
}
