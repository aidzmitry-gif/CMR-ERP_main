"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createSellerProfile, fetchSellerCurrent, fetchSellerHistory, sellerCurrency, sellerDate, sellerId, sellerKey, SellerProfileError, validSellerDraft, type SellerDraft, type SellerProfile, type SellerRequest } from "@/lib/seller-profiles-api";

type Props = { org: string; organization?: { name: string; unp: string }; onBusyChange?: (busy: boolean) => void };
const blank: SellerDraft = { effective_from: "", currency: "", address: "", account: "", bank: "", bik: "", director: "", phone: "", email: "", evidence: "", confirmed: false };
const fields = [["address", "Адрес продавца", 1000], ["account", "Расчётный счёт", 100], ["bank", "Банк продавца", 500], ["bik", "БИК", 100], ["director", "Руководитель", 300], ["phone", "Телефон", 100], ["email", "Email", 200], ["evidence", "Основание реквизитов", 2000]] as const;
export function AccountingSellerProfiles(props: Props) { return <SellerPanel key={props.org} {...props} />; }
function SellerPanel({ org, organization, onBusyChange }: Props) {
  const [history, setHistory] = useState<SellerProfile[] | null>(null), [error, setError] = useState("");
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [revision, setRevision] = useState(0);
  const [on, setOn] = useState(""), [currency, setCurrency] = useState("");
  const [query, setQuery] = useState<{ on: string; currency: string; version: number } | null>(null);
  const [initialRevision, setInitialRevision] = useState<number | null>(null);
  const lock = useCallback((value: boolean) => { setBusy(value); onBusyChange?.(value); }, [onBusyChange]);
  useEffect(() => {
    if (!sellerId(org)) return;
    let active = true;
    void fetchSellerHistory(org).then((rows) => { if (active) setHistory(rows); }).catch((e: Error) => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [org, revision]);
  const refresh = () => { setLoading(true); setError(""); setRevision((n) => n + 1); };
  return <section aria-label="Реквизиты продавца" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Реквизиты продавца</h2>
    {!sellerId(org) ? <p>Выберите юридическое лицо.</p> : <>
      <p>Юрлицо ID {org}{organization && <> · {organization.name} · УНП {organization.unp}</>}</p>
      <p className="text-sm text-muted">Наименование и УНП берутся сервером из организации. Главный бухгалтер подтверждает реквизиты для документов; это не юридическая или банковская проверка.</p>
      <fieldset disabled={busy} className="flex flex-wrap items-end gap-3">
        <label>На дату<Input aria-label="Дата действующих реквизитов" type="date" value={on} onChange={(e) => { setOn(e.target.value); setQuery(null); }} /></label>
        <label>Валюта<Input aria-label="Валюта действующих реквизитов" maxLength={3} placeholder="BYN" value={currency} onChange={(e) => { setCurrency(e.target.value.toUpperCase()); setQuery(null); }} /></label>
        <Button disabled={!sellerDate(on) || !sellerCurrency(currency)} onClick={() => setQuery({ on, currency, version: (query?.version || 0) + 1 })}>Показать действующие реквизиты</Button>
      </fieldset>
      {query && <CurrentSeller key={`${org}/${query.on}/${query.currency}/${query.version}/${revision}`} org={org} on={query.on} currency={query.currency} />}
      <div className="space-y-2">
        <h3 className="font-semibold">История реквизитов всех валют</h3>
        <p className="text-sm text-muted">Последние 100 версий юрлица, начиная с новой. Номер версии общий для всех валют. Действующие реквизиты определяются датой и валютой отдельно.</p>
        <Button variant="secondary" disabled={busy || loading} onClick={refresh}>Обновить историю реквизитов</Button>
        {loading && <p role="status">Загрузка истории реквизитов…</p>}
        {error && <p role="alert">{error} История не обновлена.</p>}
        {history?.length === 0 && !loading && !error && <p>Подтверждённых версий реквизитов пока нет.</p>}
        {history?.map((row) => <SellerCard key={row.profile_id} row={row} title="Историческая версия" />)}
      </div>
      {initialRevision === null ? <Button disabled={busy || loading || !!error || history === null} onClick={() => setInitialRevision(history?.[0]?.revision || 0)}>Подготовить новую версию реквизитов</Button>
        : <SellerForm org={org} initialRevision={initialRevision} onBusyChange={lock} onHistory={setHistory} onSaved={refresh} onNew={() => setInitialRevision(null)} />}
    </>}
  </section>;
}
function SellerCard({ row, title }: { row: SellerProfile; title: string }) {
  return <article aria-label={`${title} ${row.revision}`} className="space-y-1 rounded-lg border border-line p-3 text-sm">
    <h4 className="font-semibold">{title} {row.revision} · {row.seller.currency} · с {row.effective_from}</h4>
    <p>{row.seller.name} · УНП {row.seller.unp}</p>
    {fields.filter(([key]) => key !== "evidence").map(([key, label]) => <p key={key}>{label}: {row.seller[key as keyof typeof row.seller] || "не указан"}</p>)}
    <p>Основание: {row.evidence}</p><p>Подтвердил: {row.actor}</p>
    <details><summary>Идентификаторы сохранённой версии</summary><p>ID {row.profile_id} · юрлицо {row.organization_id}</p><p className="break-all">{row.digest}</p></details>
  </article>;
}
function CurrentSeller({ org, on, currency }: { org: string; on: string; currency: string }) {
  const [row, setRow] = useState<SellerProfile | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void fetchSellerCurrent(org, on, currency).then((r) => { if (active) setRow(r); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [org, on, currency]);
  return <div aria-label="Реквизиты на выбранную дату">{error && <p role="alert">{error}</p>}{!row && !error && <p role="status">Проверка реквизитов на дату…</p>}{row && <SellerCard row={row} title={`Действует на ${on}: версия`} />}</div>;
}
function SellerForm({ org, initialRevision, onBusyChange, onHistory, onSaved, onNew }: { org: string; initialRevision: number; onBusyChange: (value: boolean) => void; onHistory: (rows: SellerProfile[]) => void; onSaved: () => void; onNew: () => void }) {
  const [form, setForm] = useState<SellerDraft>(blank), [basis, setBasis] = useState<number | null>(initialRevision);
  const [prepared, setPrepared] = useState<SellerRequest | null>(null), [saved, setSaved] = useState<SellerProfile | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const mounted = useRef(false), posting = useRef(false), frozen = useRef<SellerRequest | null>(null);
  const callbacks = useRef({ onBusyChange, onHistory, onSaved });
  useLayoutEffect(() => { callbacks.current = { onBusyChange, onHistory, onSaved }; }, [onBusyChange, onHistory, onSaved]);
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false; callbacks.current.onBusyChange(false); }; }, []);
  async function reload() {
    if (posting.current || frozen.current) return;
    posting.current = true; setBusy(true); setError(""); callbacks.current.onBusyChange(true);
    try { const rows = await fetchSellerHistory(org); if (mounted.current) { setBasis(rows[0]?.revision || 0); callbacks.current.onHistory(rows); setForm((f) => ({ ...f, confirmed: false })); } }
    catch (e) { if (mounted.current) { setBasis(null); setError((e as Error).message); } }
    finally { posting.current = false; if (mounted.current) { setBusy(false); callbacks.current.onBusyChange(false); } }
  }
  async function submit() {
    if (posting.current || saved || (!frozen.current && (basis === null || !validSellerDraft(form)))) return;
    posting.current = true; setBusy(true); setError(""); setNotice(""); callbacks.current.onBusyChange(true);
    const retry = !!frozen.current; let unresolved = false;
    try {
      if (!retry) {
        const rows = await fetchSellerHistory(org); if (!mounted.current) return;
        const latest = rows[0]?.revision || 0; callbacks.current.onHistory(rows);
        if (latest !== basis) { setBasis(latest); setForm((f) => ({ ...f, confirmed: false })); setNotice("Глобальная версия юрлица изменилась. Проверьте основу и подтвердите реквизиты заново."); return; }
        const draft = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, typeof v === "string" ? v.trim() : v])) as SellerDraft;
        frozen.current = { ...draft, expected_revision: latest, source_key: sellerKey() }; setPrepared(frozen.current);
      }
      unresolved = true;
      const row = await createSellerProfile(org, frozen.current!); if (!mounted.current) return;
      unresolved = false; frozen.current = null; setPrepared(null); setSaved(row); setNotice(`Версия ${row.revision} сохранена сервером.`); callbacks.current.onSaved();
    } catch (e) {
      if (mounted.current) {
        setError((e as Error).message);
        if (!retry && e instanceof SellerProfileError && [401, 403, 404, 409, 422].includes(e.status || 0)) { unresolved = false; frozen.current = null; setPrepared(null); setBasis(null); setForm((f) => ({ ...f, confirmed: false })); }
      }
    } finally { posting.current = false; if (mounted.current) { setBusy(false); if (!unresolved) callbacks.current.onBusyChange(false); } }
  }
  return <section aria-label="Новая версия реквизитов" className="space-y-3 rounded-lg border border-accent p-3">
    <h3 className="font-semibold">Новая версия реквизитов</h3>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {saved ? <><SellerCard row={saved} title="Фактически сохранена версия" /><Button variant="secondary" disabled={busy} onClick={onNew}>Подготовить следующую версию</Button></> : <>
      <p>Основа: глобальная версия {basis === null ? "требует обновления" : basis} юрлица ID {org}.</p>
      <Button variant="secondary" disabled={busy || !!prepared} onClick={() => void reload()}>Обновить основу версии</Button>
      <fieldset disabled={busy || !!prepared} className="grid gap-3 md:grid-cols-2">
        <label>Начало действия<Input aria-label="Начало действия реквизитов" type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value, confirmed: false })} /></label>
        <label>Валюта новой версии<Input aria-label="Валюта новой версии" maxLength={3} placeholder="BYN" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase(), confirmed: false })} /></label>
        {fields.map(([key, label, max]) => <label key={key}>{label}{(key === "phone" || key === "email") && " (необязательно)"}<Input aria-label={label} maxLength={max} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value, confirmed: false })} /></label>)}
        <label className="md:col-span-2"><input type="checkbox" aria-label="Реквизиты проверены главным бухгалтером" checked={form.confirmed} onChange={(e) => setForm({ ...form, confirmed: e.target.checked })} /> Подтверждаю реквизиты для документов выбранного юрлица по указанному основанию.</label>
      </fieldset>
      <Button disabled={busy || (!prepared && (basis === null || !validSellerDraft(form)))} onClick={() => void submit()}>{busy ? "Проверка и сохранение…" : prepared ? "Повторить сохранённый запрос" : "Подтвердить версию реквизитов"}</Button>
      {prepared && <p>Результат отправки неизвестен. Поля и переходы зафиксированы; повтор отправит те же реквизиты с тем же автоматически созданным ключом.</p>}
    </>}
  </section>;
}
