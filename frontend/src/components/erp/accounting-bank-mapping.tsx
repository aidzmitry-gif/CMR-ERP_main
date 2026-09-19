"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

export type MappingAccount = { id: number; code: string; title: string; cash: boolean; valid_from?: string; required_dimensions: string[] };
type Mapping = {
  mapping_id: number;
  provider: string;
  external_account: string;
  currency: string;
  valid_from: string;
  valid_to: string | null;
  version: number;
  ledger_account_id: number;
  dimensions: Record<string, string>;
};

function message(body: unknown, fallback: string) {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? String((body as { detail: string }).detail)
    : fallback;
}

export function AccountingBankMapping({ org, accounts, onChanged }: {
  org: string;
  accounts: MappingAccount[];
  onChanged: () => void;
}) {
  const sequence = useRef(0);
  const accountsSequence = useRef(0);
  const currentOrg = useRef(org);
  const [rows, setRows] = useState<Mapping[]>([]);
  const [datedAccounts, setDatedAccounts] = useState<MappingAccount[]>([]);
  const [provider, setProvider] = useState("");
  const [externalAccount, setExternalAccount] = useState("");
  const [currency, setCurrency] = useState("BYN");
  const [validFrom, setValidFrom] = useState("");
  const [ledgerAccountId, setLedgerAccountId] = useState("");
  const [dimensions, setDimensions] = useState<Record<string, string>>({});
  const [evidence, setEvidence] = useState("");
  const [closing, setClosing] = useState<number | null>(null);
  const [validTo, setValidTo] = useState("");
  const [closeEvidence, setCloseEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!org) return;
    const request = ++sequence.current;
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-account-mappings?include_closed=true`, { cache: "no-store" });
      const body = await response.json();
      if (request !== sequence.current) return;
      if (!response.ok) throw new Error(message(body, "Не удалось загрузить registry банковских счетов."));
      setRows(body as Mapping[]);
    } catch (cause) {
      if (request === sequence.current) setError(cause instanceof Error ? cause.message : "Не удалось загрузить registry банковских счетов.");
    }
  }, [org]);

  // Organisation boundaries are security boundaries: never render or mutate
  // data obtained for a previous organisation.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    currentOrg.current = org;
    sequence.current += 1;
    setRows([]); setProvider(""); setExternalAccount(""); setCurrency("BYN"); setValidFrom("");
    setLedgerAccountId(""); setDimensions({}); setEvidence(""); setClosing(null); setValidTo(""); setCloseEvidence(""); setError("");
    void load();
  }, [org, load]);

  // The parent list is only a display cache. Create must resolve accounts from
  // the accounting API at the requested effective date.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => {
    const request = ++accountsSequence.current;
    if (!org || !validFrom) { setDatedAccounts([]); return; }
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/accounts?on=${encodeURIComponent(validFrom)}`, { cache: "no-store" });
        const body = await response.json();
        if (request !== accountsSequence.current || currentOrg.current !== org) return;
        if (!response.ok) throw new Error(message(body, "Не удалось получить план счетов на выбранную дату."));
        setDatedAccounts(body as MappingAccount[]);
      } catch (cause) {
        if (request === accountsSequence.current && currentOrg.current === org) {
          setDatedAccounts([]); setError(cause instanceof Error ? cause.message : "Не удалось получить план счетов на выбранную дату.");
        }
      }
    })();
  }, [org, validFrom]);

  async function create() {
    const scope = org;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-account-mappings`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, external_account: externalAccount, currency, valid_from: validFrom,
          ledger_account_id: Number(ledgerAccountId), dimensions, evidence }),
      });
      const body = await response.json();
      if (currentOrg.current !== scope) return;
      if (!response.ok) throw new Error(message(body, "Не удалось создать mapping."));
      setProvider(""); setExternalAccount(""); setValidFrom(""); setLedgerAccountId(""); setDimensions({}); setEvidence("");
      await load(); onChanged();
    } catch (cause) { if (currentOrg.current === scope) setError(cause instanceof Error ? cause.message : "Не удалось создать привязку."); }
    finally { setBusy(false); }
  }

  async function close() {
    if (closing === null) return;
    const scope = org;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-account-mappings/${closing}/close`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ valid_to: validTo, evidence: closeEvidence }),
      });
      const body = await response.json();
      if (currentOrg.current !== scope) return;
      if (!response.ok) throw new Error(message(body, "Не удалось закрыть привязку."));
      setClosing(null); setValidTo(""); setCloseEvidence("");
      await load(); onChanged();
    } catch (cause) { if (currentOrg.current === scope) setError(cause instanceof Error ? cause.message : "Не удалось закрыть привязку."); }
    finally { setBusy(false); }
  }

  const selectedAccount = datedAccounts.find((account) => account.id === Number(ledgerAccountId));

  return <section aria-label="Привязки банковских счетов" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <div><h3 className="font-semibold">Привязки банковских счетов</h3><p className="text-sm text-muted">Укажите источник выписки, счёт и действующую версию денежного счёта.</p></div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <div className="overflow-x-auto rounded border border-line"><table className="w-full text-left text-sm"><thead><tr className="border-b border-line text-muted"><th className="p-2">Источник выписки / счёт</th><th className="p-2">Валюта / период</th><th className="p-2">Счёт / аналитики</th><th className="p-2" /></tr></thead><tbody>{rows.map((row) => {
      const account = accounts.find((item) => item.id === row.ledger_account_id);
      const analytics = Object.entries(row.dimensions || {}).map(([key, value]) => `${key}: ${value}`).join(" · ") || "Нет аналитик";
      return <tr key={row.mapping_id} className="border-b border-line last:border-0"><td className="p-2">{row.provider}<br /><span className="text-muted">{row.external_account} · v{row.version}</span></td><td className="p-2">{row.currency}<br /><span className="text-muted">{row.valid_from} — {row.valid_to || "текущая"}</span></td><td className="p-2">{account ? `${account.code} · ${account.title}` : `ID ${row.ledger_account_id}`}<br /><span className="text-muted">{analytics}</span></td><td className="p-2 text-right">{!row.valid_to && <Button variant="secondary" disabled={busy} onClick={() => setClosing(row.mapping_id)}>Закрыть</Button>}</td></tr>;
    })}</tbody></table></div>
    {closing !== null && <div className="grid gap-2 rounded border border-accent p-3 md:grid-cols-3"><label>Дата закрытия<Input aria-label="Дата закрытия привязки" type="date" value={validTo} disabled={busy} onChange={(event) => setValidTo(event.target.value)} /></label><label className="md:col-span-2">Основание<Input aria-label="Основание закрытия привязки" value={closeEvidence} disabled={busy} onChange={(event) => setCloseEvidence(event.target.value)} /></label><div className="flex gap-2"><Button disabled={busy || !validTo || closeEvidence.length < 10} onClick={() => void close()}>Подтвердить закрытие</Button><Button variant="secondary" disabled={busy} onClick={() => setClosing(null)}>Отмена</Button></div></div>}
    <div className="grid gap-2 rounded border border-line p-3 md:grid-cols-3"><h4 className="font-medium md:col-span-3">Создать привязку</h4><label>Источник выписки<Input aria-label="Источник выписки" value={provider} disabled={busy} onChange={(event) => setProvider(event.target.value)} /></label><label>Внешний счёт<Input aria-label="Внешний счёт привязки" value={externalAccount} disabled={busy} onChange={(event) => setExternalAccount(event.target.value)} /></label><label>Валюта<Input aria-label="Валюта привязки" value={currency} disabled={busy} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></label><label>Действует с<Input aria-label="Дата начала привязки" type="date" value={validFrom} disabled={busy} onChange={(event) => { setValidFrom(event.target.value); setLedgerAccountId(""); setDimensions({}); }} /></label><label>Денежный счёт<Select aria-label="Денежный счёт привязки" value={ledgerAccountId} disabled={busy || !validFrom} onChange={(event) => { setLedgerAccountId(event.target.value); setDimensions({}); }}><option value="">Выберите счёт</option>{datedAccounts.filter((account) => account.cash).map((account) => <option key={account.id} value={account.id}>{account.code} · {account.title}</option>)}</Select></label>{selectedAccount?.required_dimensions.map((key) => <label key={key}>Аналитика: {key}<Input aria-label={`Аналитика привязки: ${key}`} value={dimensions[key] || ""} disabled={busy} onChange={(event) => setDimensions({ ...dimensions, [key]: event.target.value })} /></label>)}<label className="md:col-span-3">Основание<Input aria-label="Основание привязки" value={evidence} disabled={busy} onChange={(event) => setEvidence(event.target.value)} /></label><Button disabled={busy || !provider || !externalAccount || !validFrom || !ledgerAccountId || evidence.length < 10 || !!selectedAccount?.required_dimensions.some((key) => !dimensions[key])} onClick={() => void create()}>Создать привязку</Button></div>
  </section>;
}
