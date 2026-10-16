"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { DocumentRegisterError, registerId } from "@/lib/document-register-api";
import { claimClientBinding, fetchClientOptions, previewClientBinding, type BindingClaim, type BindingPreview, type ClientBinding, type ClientOption } from "@/lib/client-document-register-api";

export function DealClientBinding({ org, dealId, onBound }: { org: string; dealId: string; onBound?: () => void }) {
  return <BindingCard key={`${org}/${dealId}`} org={org} dealId={dealId} onBound={onBound} />;
}

function BindingCard({ org, dealId, onBound }: { org: string; dealId: string; onBound?: () => void }) {
  const [client, setClient] = useState("");
  const [clientSearch, setClientSearch] = useState("");
  const [clientOptions, setClientOptions] = useState<ClientOption[]>([]);
  const [lookupError, setLookupError] = useState("");
  const [evidence, setEvidence] = useState("");
  const [preview, setPreview] = useState<BindingPreview | null>(null);
  const [prepared, setPrepared] = useState<BindingClaim | null>(null);
  const [confirmed, setConfirmed] = useState<ClientBinding | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false), posting = useRef(false), previewBusy = useRef(false);
  const generation = useRef(0), callback = useRef(onBound);
  useLayoutEffect(() => { callback.current = onBound; }, [onBound]);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current += 1; }; }, []);
  useEffect(() => {
    const term = clientSearch.trim();
    if (!term) return;
    let current = true;
    const timer = window.setTimeout(() => {
      void fetchClientOptions(org, dealId, term)
        .then((items) => { if (current) { setClientOptions(items); setLookupError(""); } })
        .catch((cause: Error) => { if (current) { setClientOptions([]); setLookupError(cause.message); } });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [org, dealId, clientSearch]);
  function changeClient(value: string) {
    generation.current += 1; previewBusy.current = false;
    setClient(value); setPreview(null); setPrepared(null); setConfirmed(null); setError(""); setBusy(false);
  }
  async function inspect() {
    if (previewBusy.current || posting.current || !registerId(org) || !registerId(dealId) || !registerId(client)) return;
    const token = ++generation.current;
    previewBusy.current = true; setBusy(true); setError(""); setPreview(null); setPrepared(null); setConfirmed(null);
    try {
      const value = await previewClientBinding(org, dealId, client);
      if (mounted.current && token === generation.current) { setPreview(value); if (value.assigned) setConfirmed(value.binding); }
    } catch (e) { if (mounted.current && token === generation.current) setError((e as Error).message); }
    finally { if (mounted.current && token === generation.current) { previewBusy.current = false; setBusy(false); } }
  }
  async function confirm() {
    if (posting.current || busy || !preview || preview.assigned || confirmed || !evidence.trim()) return;
    const body = prepared || { counterparty_id: Number(client), expected_snapshot: preview.snapshot, evidence: evidence.trim() };
    const token = generation.current;
    posting.current = true; setPrepared(body); setBusy(true); setError("");
    try {
      const value = await claimClientBinding(org, dealId, body);
      if (mounted.current && token === generation.current) { setConfirmed(value); callback.current?.(); }
    } catch (e) {
      if (mounted.current && token === generation.current) {
        setError((e as Error).message);
        // Definitive rejection invalidates the reviewed facts. An ambiguous
        // network/invalid-response error keeps the identical payload for retry.
        if (e instanceof DocumentRegisterError && e.status && e.status >= 400 && e.status < 500) { setPreview(null); setPrepared(null); }
      }
    } finally { posting.current = false; if (mounted.current && token === generation.current) setBusy(false); }
  }
  return <section aria-label="Подтверждение клиента сделки" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h3 className="font-semibold">Подтвердить клиента сделки</h3>
    <p className="text-sm text-muted">Юрлицо ID {org || "не выбрано"} · сделка ID {dealId}. Подтверждает главный бухгалтер по первичным основаниям. Совпадение названий не связывает клиентов.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <label className="block text-sm">Поиск покупателя<Input aria-label="Поиск покупателя в справочнике" maxLength={100} value={clientSearch} disabled={!!prepared || !!confirmed || !registerId(org) || !registerId(dealId)} onChange={(e) => { setClientSearch(e.target.value); setClientOptions([]); setLookupError(""); changeClient(""); }} /></label>
    <label className="block text-sm">Покупатель из справочника<Select aria-label="Покупатель из справочника" value={client} disabled={!!prepared || !!confirmed || !registerId(org) || !registerId(dealId)} onChange={(e) => changeClient(e.target.value)}><option value="">Выберите покупателя</option>{clientOptions.map((option) => <option key={option.id} value={option.id}>{option.name} · {option.unp || "без УНП"} · ID {option.id}</option>)}</Select></label>
    {lookupError && <p role="alert">Справочник покупателей недоступен: {lookupError}</p>}
    <Button variant="secondary" disabled={busy || !!prepared || !!confirmed || !registerId(org) || !registerId(dealId) || !registerId(client)} onClick={() => void inspect()}>Просмотреть привязку клиента</Button>
    {busy && <p role="status">Проверка привязки…</p>}
    {preview && !confirmed && <div className="space-y-2 rounded-lg border border-accent p-3 text-sm">
      <p className="font-semibold">Проверяемый клиент ID {preview.snapshot.client.id} · {preview.snapshot.client.name} · УНП {preview.snapshot.client.unp || "не указан"}</p>
      <p>Версия MDM {preview.snapshot.client.revision} · {preview.snapshot.client.is_active ? "активен" : "неактивен"}</p>
      <p>Сделка {preview.snapshot.deal.number} · ID {preview.snapshot.deal.id} · текущее название покупателя: {preview.snapshot.deal.counterparty} · ответственный ID {preview.snapshot.deal.owner_id ?? "не указан"}</p>
      <p>Просмотренные версии документов: {preview.snapshot.documents.length}</p>
      {preview.snapshot.documents.map((doc) => <div key={doc.id} className="break-all">
        <p>{doc.kind} · {doc.number} · ID {doc.id} · версия {doc.version} · сумма {doc.amount} · статус {doc.status}</p>
        <p>Заменяет ID {doc.supersedes_id ?? "нет"} · заменён ID {doc.superseded_by_id ?? "нет"} · хеш сохранённого содержания: {doc.content_sha256 || "не сохранён"}</p>
      </div>)}
      <label className="block">Первичное основание<Input aria-label="Основание привязки клиента" maxLength={1000} value={evidence} disabled={busy || !!prepared} onChange={(e) => setEvidence(e.target.value)} /></label>
      <Button disabled={busy || !evidence.trim()} onClick={() => void confirm()}>{prepared ? "Повторить подтверждение с теми же фактами" : "Подтвердить клиента сделки"}</Button>
      {prepared && !busy && <p>Результат предыдущего запроса не подтверждён. Повтор использует тот же просмотренный состав и основание.</p>}
    </div>}
    {confirmed && <div role="status" className="space-y-1 rounded-lg border border-line p-3 text-sm">
      <p className="font-semibold">Клиент ID {confirmed.counterparty_id} подтверждён для сделки ID {confirmed.deal_id}.</p>
      <p>{confirmed.snapshot.client.name} · УНП {confirmed.snapshot.client.unp || "не указан"} — реквизиты на момент подтверждения.</p>
      <p>Основание: {confirmed.evidence}</p><p>Подтвердил: {confirmed.actor} · {confirmed.created_at}</p>
      <a className="text-accent underline" href={`/erp/spravochniki/counterparty/${confirmed.counterparty_id}`}>Открыть карточку подтверждённого клиента</a>
      <p>Изменение принадлежности и перенос при слиянии MDM требуют отдельного протокола.</p>
    </div>}
  </section>;
}
