"use client";

import { useEffect, useRef, useState } from "react";

import { DealClientBinding } from "@/components/deal-client-binding";
import { InvoicePhysicalShipment } from "@/components/erp/invoice-physical-shipment";
import { InvoiceCancellation } from "@/components/erp/invoice-cancellation";
import { InvoiceNotificationRegister } from "@/components/invoice-notification-register";
import { ShipmentDocumentDraft } from "@/components/erp/shipment-document-draft";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { fetchDocumentRegister, fetchRegisterDocument, fetchRegisterOrganizations, fetchRegisterOriginal, registerId,
  type DocumentRegisterItem, type DocumentRegisterPage, type RegisterOrganization } from "@/lib/document-register-api";

const kinds: Record<string, string> = { invoice: "Счёт", contract: "Договор", order: "Заказ" };
const statuses: Record<string, string> = { issued: "Выпущен", draft: "Черновик", posted: "Выпущен / проведён", paid: "Статус документа: оплачен", pending_approval: "На согласовании", cancelled: "Аннулирован", rejected: "Отклонён" };
const reserves: Record<string, string> = { unreserved: "Без резерва", none: "Нет резерва", reserved: "Зарезервирован", consumed: "Исторический статус резерва: требуется сверка", released: "Резерв снят" };
const message = (e: unknown) => e instanceof Error ? e.message : "Не удалось загрузить документы.";

export function DealDocumentRegister({ dealId, org, initialDocumentId }: { dealId: string; org?: string; initialDocumentId?: number }) {
  return <RegisterSelection key={`${dealId}/${org || ""}/${initialDocumentId ?? ""}`} dealId={dealId} confirmedOrg={org} initialDocumentId={Number.isSafeInteger(initialDocumentId) && initialDocumentId! > 0 ? initialDocumentId : undefined} />;
}

function RegisterSelection({ dealId, confirmedOrg, initialDocumentId }: { dealId: string; confirmedOrg?: string; initialDocumentId?: number }) {
  const [organizations, setOrganizations] = useState<RegisterOrganization[] | null>(null);
  const [org, setOrg] = useState(confirmedOrg || "");
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (confirmedOrg || !registerId(dealId)) return;
    let active = true;
    void fetchRegisterOrganizations().then((rows) => { if (active) setOrganizations(rows); })
      .catch((e: unknown) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [confirmedOrg, dealId, revision]);
  return <section aria-label="Реестр документов сделки" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Реестр документов сделки</h2>
    {!registerId(dealId) ? <p role="alert">Некорректный ID сделки.</p> : <>
      <p className="text-sm text-muted">Сделка ID {dealId}. Выберите юридическое лицо, которому принадлежит сделка.</p>
      {confirmedOrg ? <p>Юрлицо ID {confirmedOrg}</p> : <>
        <label className="block text-sm">Юрлицо реестра<Select aria-label="Юрлицо реестра" value={org} disabled={!organizations} onChange={(e) => setOrg(e.target.value)}><option value="">Выберите юридическое лицо</option>{organizations?.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}</Select></label>
        {!organizations && !error && <p role="status">Загрузка доступных книг…</p>}
        {organizations?.length === 0 && <p>Доступных книг нет.</p>}
      </>}
      {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" onClick={() => { setError(""); setRevision((n) => n + 1); }}>Повторить загрузку книг</Button></>}
      {org && !registerId(org) && <p role="alert">Некорректный ID юрлица.</p>}
      {registerId(org) && <RegisterBody key={`${org}/${dealId}`} org={org} dealId={dealId} initialDocumentId={initialDocumentId} />}
    </>}
  </section>;
}

function RegisterBody({ org, dealId, initialDocumentId }: { org: string; dealId: string; initialDocumentId?: number }) {
  const [kind, setKind] = useState("");
  const [bindingRevision, setBindingRevision] = useState(0);
  return <div className="space-y-3">
    <p className="text-xs text-muted">Здесь показаны документы выбранной сделки. Принадлежность клиенту определяется подтверждённой связью.</p>
    <label className="block text-sm">Вид документа<Select aria-label="Вид документа реестра" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Все виды</option>{Object.entries(kinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Select></label>
    <DealClientBinding org={org} dealId={dealId} onBound={() => setBindingRevision((n) => n + 1)} />
    <RegisterPage key={`${kind}/${bindingRevision}`} org={org} dealId={dealId} kind={kind} initialDocumentId={initialDocumentId} />
    <p className="text-xs text-muted">Подтверждённые оплаты и возвраты доступны в отдельном регистре главного бухгалтера. Статус «оплачен» не заменяет первичные основания.</p>
    <p className="text-xs text-muted">Реестр показывает внутренние акты WMS; они не заменяют ТН/ТТН. Официальный источник ТН/ТТН подключается отдельно.</p>
  </div>;
}

function RegisterPage({ org, dealId, kind, initialDocumentId }: { org: string; dealId: string; kind: string; initialDocumentId?: number }) {
  const [page, setPage] = useState<DocumentRegisterPage | null>(null);
  const [cursor, setCursor] = useState(0);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<number | null>(initialDocumentId ?? null);
  const pageClick = useRef(false);
  useEffect(() => {
    let active = true;
    void fetchDocumentRegister(org, dealId, kind, cursor).then((data) => {
      if (active) setPage((previous) => cursor && previous ? { ...data, items: [...previous.items, ...data.items], shipment_documents: [...previous.shipment_documents, ...data.shipment_documents.filter((row) => !previous.shipment_documents.some((old) => old.act_id === row.act_id))] } : data);
    }).catch((e: unknown) => { if (active) setError(message(e)); })
      .finally(() => { if (active) { setLoading(false); pageClick.current = false; } });
    return () => { active = false; };
  }, [org, dealId, kind, cursor, revision]);
  function more() {
    if (pageClick.current || loading || !page?.next_after_id) return;
    pageClick.current = true; setLoading(true); setError(""); setSelected(null); setCursor(page.next_after_id);
  }
  return <div className="space-y-3">
    {loading && <p role="status">Загрузка реестра…</p>}
    {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" disabled={loading} onClick={() => { setLoading(true); setError(""); setRevision((n) => n + 1); }}>Повторить загрузку реестра</Button></>}
    {page?.client_identity.status === "confirmed" && <p className="text-sm">Подтверждённый клиент ID {page.client_identity.counterparty_id} · {page.client_identity.snapshot.name} · УНП {page.client_identity.snapshot.unp || "не указан"}. Реквизиты на момент подтверждения.</p>}
    {page?.client_identity.status === "unresolved" && <p className="text-sm text-muted">Клиент сделки ещё не подтверждён. В общий реестр клиента она не включается.</p>}
    {page && <ShipmentDocuments page={page} />}
    {page?.items.length === 0 && !error && !loading && <p>В этом реестре документы по фильтру не найдены.</p>}
    {page?.items.map((row) => <DocumentRow key={row.id} row={row} onSelect={setSelected} />)}
    {page?.next_after_id !== null && page && !error && <Button variant="secondary" disabled={loading} onClick={more}>Ещё документы</Button>}
    {selected !== null && <SelectedDocument key={selected} org={org} dealId={dealId} id={selected} onSelect={setSelected} onClose={() => setSelected(null)} onCancelled={() => { setCursor(0); setRevision(n => n + 1); }} />}
  </div>;
}

function ShipmentDocuments({ page }: { page: DocumentRegisterPage }) {
  if (page.coverage.shipments === "unavailable") return <p className="text-xs text-muted">Реестр внутренних актов отгрузки недоступен. Это не означает отсутствия отгрузок.</p>;
  return <section aria-label="Внутренние акты отгрузки" className="space-y-2 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">Внутренние акты отгрузки</h3>
    <p className="text-xs text-muted">Акты WMS подтверждены источником и уменьшают резерв. Они не являются ТН или ТТН; из каждого акта можно подготовить проверяемый черновик реквизитов.</p>
    {page.shipment_documents.length === 0 ? <p>Подтверждённых внутренних актов по документам этой страницы нет.</p> : <ul className="space-y-1">{page.shipment_documents.map((row) => <li key={row.act_id}>
      <a className="text-accent underline" href={row.document_url} target="_blank" rel="noreferrer">Акт WMS № {row.act_id}</a>
      <span> · счёт ID {row.document_id} · дата {row.operation_date} · строк {row.line_count} · {row.actor}</span>
      <ShipmentDocumentDraft org={String(page.organization_id)} sourceKey={row.source_key} />
    </li>)}</ul>}
  </section>;
}

function DocumentRow({ row, onSelect, detail = false }: { row: DocumentRegisterItem; onSelect: (id: number) => void; detail?: boolean }) {
  return <article aria-label={`Версия документа ${row.id}`} className="space-y-1 rounded-lg border border-line p-3 text-sm">
    <h3 className="font-semibold">{kinds[row.kind] || row.kind} · {row.number} · версия {row.version} · ID {row.id}</h3>
    <p className="tabular-nums">{row.amount} {row.currency || "Валюта неизвестна"}</p>
    <p>{statuses[row.status] || row.status} · {reserves[row.reserve_status] || row.reserve_status}</p>
    <p>Выпущен: {row.issued_at || "не указан"} · Срок действия по оригиналу: {row.valid_until || "не указан"}</p>
    {row.kind === "invoice" && row.expiry_reminder_at && ["issued", "posted"].includes(row.status)
      && row.reserve_status === "reserved" && row.superseded_by_id === null && <p role="alert" className="rounded border border-amber-400 p-2">
        Требуется проверка срока действия счёта: {row.valid_until || "дата не указана"}.
        Перед аннулированием проверьте оплаты, возвраты и отгрузки. Резерв сохранён.
      </p>}
    {row.replacement_reason && <p>Причина замены: {row.replacement_reason}</p>}
    {row.onec_ref && <p>Ссылка 1С: {row.onec_ref}</p>}
    {row.original_state === "legacy_unavailable" && <p className="text-muted">Оригинал не сохранён. Историческое содержание неизвестно.</p>}
    {row.original_state === "draft" && <p className="text-muted">Черновик — не исторический оригинал.</p>}
    {row.original_state === "approval_copy" && <p className="text-muted">Сохранённая копия на согласовании — ещё не выпущена.</p>}
    {row.content_sha256 && <details><summary className="cursor-pointer text-accent">Хеш оригинала</summary><p className="break-all">{row.content_sha256}</p></details>}
    <div className="flex flex-wrap gap-2">
      {!detail && <Button variant="secondary" onClick={() => onSelect(row.id)}>Открыть версию ID {row.id}</Button>}
      {row.supersedes_id !== null && <Button variant="ghost" onClick={() => onSelect(row.supersedes_id!)}>Заменяет ID {row.supersedes_id}</Button>}
      {row.superseded_by_id !== null && <Button variant="ghost" onClick={() => onSelect(row.superseded_by_id!)}>Заменён ID {row.superseded_by_id}</Button>}
    </div>
  </article>;
}

function SelectedDocument({ org, dealId, id, onSelect, onClose, onCancelled }: { org: string; dealId: string; id: number; onSelect: (id: number) => void; onClose: () => void; onCancelled: () => void }) {
  const [cancellation, setCancellation] = useState(false);
  const [shipment, setShipment] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [row, setRow] = useState<DocumentRegisterItem | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [original, setOriginal] = useState(false);
  useEffect(() => {
    let active = true;
    void fetchRegisterDocument(org, dealId, id).then((data) => { if (active) setRow(data); })
      .catch((e: unknown) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [org, dealId, id, revision]);
  return <section aria-label="Выбранная версия" className="space-y-3 rounded-xl border border-accent p-3">
    <Button variant="ghost" onClick={onClose}>Закрыть версию</Button>
    {!row && !error && <p role="status">Загрузка версии ID {id}…</p>}
    {error && <><p role="alert" className="text-red-700">{error}</p><Button variant="secondary" onClick={() => { setError(""); setRevision((n) => n + 1); }}>Повторить загрузку версии</Button></>}
    {row && <><DocumentRow row={row} onSelect={onSelect} detail />
      {row.kind === "invoice" && <Button variant="secondary" onClick={() => setCancellation(true)}>Аннулирование счёта</Button>}
      {cancellation && row.kind === "invoice" && <InvoiceCancellation scope={{ org: Number(org), deal: Number(dealId), document: id }} onCancelled={() => { setRevision(n => n + 1); onCancelled(); }} />}
      {row.kind === "invoice" && <Button variant="secondary" onClick={() => setShipment(true)}>Фактическая отгрузка и акты</Button>}
      {row.kind === "invoice" && <Button variant="secondary" onClick={() => setNotifications(true)}>Уведомления клиенту</Button>}
      {notifications && row.kind === "invoice" && <InvoiceNotificationRegister organizationId={Number(org)} dealId={dealId} documentId={id} />}
      {shipment && row.kind === "invoice" && <InvoicePhysicalShipment scope={{ organization_id: Number(org), deal_id: Number(dealId), document_id: id }} />}
      {row.original_available && <Button variant="secondary" onClick={() => setOriginal(true)}>{row.original_state === "approval_copy" ? "Открыть сохранённую копию" : "Открыть оригинал"} ID {id}</Button>}
      {original && <Original org={org} dealId={dealId} id={id} onClose={() => setOriginal(false)} />}
    </>}
  </section>;
}

function Original({ org, dealId, id, onClose }: { org: string; dealId: string; id: number; onClose: () => void }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void fetchRegisterOriginal(org, dealId, id).then((value) => { if (active) setHtml(value); })
      .catch((e: unknown) => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [org, dealId, id]);
  return <div className="space-y-2">
    <Button variant="ghost" onClick={onClose}>Закрыть оригинал</Button>
    {!html && !error && <p role="status">Проверка оригинала…</p>}
    {error && <p role="alert" className="text-red-700">{error} Предпросмотр не подставляется вместо оригинала.</p>}
    {html !== null && <iframe title={`Сохранённый оригинал ID ${id}`} sandbox="" referrerPolicy="no-referrer" srcDoc={html} className="h-[32rem] w-full rounded-lg border border-line bg-white" />}
  </div>;
}
