"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type Account = { code: string; title: string; cash: boolean; category: string; required_dimensions: string[] };
type Snapshot = {
  transaction_id: number;
  ext_id: string;
  occurred_on: string | null;
  amount: string | null;
  currency: string;
  payer_unp: string | null;
  payer_name: string | null;
  purpose: string | null;
  account_code: string | null;
  match_status: string;
};
type Candidate = {
  source_snapshot: Snapshot;
  source_digest: string | null;
  binding_status: "unbound" | "own" | "other";
  imported: boolean;
  entry_id: number | null;
};
type Preview = {
  basis_digest: string;
  digest: string;
  source_snapshot: Snapshot;
  lines: { account: string; title: string; side: string; amount: string; dimensions?: Record<string, string> }[];
  confirmation_available: boolean;
  normative_verified: boolean;
};

function message(body: unknown, fallback: string) {
  return typeof body === "object" && body !== null && typeof (body as { detail?: unknown }).detail === "string"
    ? String((body as { detail: string }).detail)
    : fallback;
}

export function AccountingBankImport({ org, accounts, policyId, date, onDate, onPosted, onEntry }: {
  org: string;
  accounts: Account[];
  policyId?: number;
  date: string;
  onDate: (date: string) => void;
  onPosted: () => void;
  onEntry?: (id: number) => void;
}) {
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [bankAccount, setBankAccount] = useState("");
  const [settlementAccount, setSettlementAccount] = useState("");
  const [bankDimensions, setBankDimensions] = useState<Record<string, string>>({});
  const [settlementDimensions, setSettlementDimensions] = useState<Record<string, string>>({});
  const [cashActivity, setCashActivity] = useState("operating");
  const [explanation, setExplanation] = useState("");
  const [requestKey, setRequestKey] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prepared, setPrepared] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selected = candidates.find((candidate) => candidate.source_snapshot.transaction_id === selectedId) ?? null;
  const cashAccounts = useMemo(() => accounts.filter((account) => account.cash), [accounts]);
  const settlementAccounts = useMemo(
    () => accounts.filter((account) => !account.cash && ["asset", "liability"].includes(account.category)),
    [accounts],
  );

  const load = useCallback(async () => {
    if (!org) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-import/candidates`, { cache: "no-store" });
      const body = await response.json();
      if (!alive.current) return;
      if (!response.ok) throw new Error(message(body, "Не удалось загрузить очередь банковских строк."));
      setCandidates(body as Candidate[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить очередь банковских строк.");
    } finally {
      setLoading(false);
    }
  }, [org]);

  // The effect owns the remote queue refresh; the async callback updates the
  // view only after the response, so the state change is intentionally tied to
  // the external source rather than to render.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  function select(candidate: Candidate) {
    setSelectedId(candidate.source_snapshot.transaction_id);
    setBankDimensions({}); setSettlementDimensions({});
    setBankAccount(cashAccounts[0]?.code ?? "");
    setSettlementAccount(settlementAccounts[0]?.code ?? "");
    setExplanation(candidate.source_snapshot.purpose || `Банковская строка ${candidate.source_snapshot.ext_id}`);
    setRequestKey(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${candidate.source_snapshot.transaction_id}`);
    setPreview(null);
    setPrepared(null);
    setNotice("");
  }

  async function bind(candidate: Candidate) {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/source-bindings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_type: "finance_bank_transaction",
          source_id: candidate.source_snapshot.transaction_id,
          ownership: "own",
          evidence: `Банковская строка ${candidate.source_snapshot.ext_id} сопоставлена с выбранным юрлицом бухгалтером.`,
        }),
      });
      const body = await response.json();
      if (!alive.current) return;
      if (!response.ok) throw new Error(message(body, "Не удалось закрепить банковскую строку за юрлицом."));
      setNotice(`Строка ${candidate.source_snapshot.ext_id} привязана к выбранному юрлицу.`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось закрепить банковскую строку за юрлицом."); }
    finally { setBusy(false); }
  }

  async function execute(confirm: boolean) {
    if (!selected) return;
    if (!policyId) { setError("Сначала утвердите учётную политику на дату отражения."); return; }
    const body = confirm ? { ...prepared, basis_digest: preview?.basis_digest, digest: preview?.digest } : {
      request_key: requestKey,
      source_transaction_id: selected.source_snapshot.transaction_id,
      source_digest: selected.source_digest,
      policy_id: policyId,
      bank_account: bankAccount,
      settlement_account: settlementAccount,
      bank_dimensions: bankDimensions,
      settlement_dimensions: settlementDimensions,
      posting_date: date,
      cash_activity: cashActivity,
      explanation,
    };
    if (!body) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/bank-import/${confirm ? "confirm" : "preview"}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!alive.current) return;
      if (!response.ok) throw new Error(message(result, "Проверьте источник, политику и счета."));
      if (confirm) {
        setSelectedId(null); setPreview(null); setPrepared(null);
        setNotice(`Строка ${selected.source_snapshot.ext_id} проведена в бухгалтерскую книгу.`);
        await load();
        if (alive.current) onPosted();
      } else {
        setPrepared(body as Record<string, unknown>);
        setPreview(result as Preview);
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Операция импорта не выполнена."); }
    finally { setBusy(false); }
  }

  return <section aria-label="Импорт банковских строк" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div>
      <h2 className="font-semibold">Импорт выписки в бухгалтерскую книгу</h2>
      <p className="mt-1 text-sm text-muted">Сырые строки принадлежат finance. Сначала закрепите строку за юрлицом, затем проверьте точные счета и проведите её через предварительный расчёт.</p>
    </div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status" className="text-money">{notice}</p>}
    <div className="flex items-end gap-3">
      <label className="text-sm">Дата отражения<Input aria-label="Дата отражения импорта" type="date" value={date} disabled={busy} onChange={(event) => { setPreview(null); setPrepared(null); onDate(event.target.value); }} /></label>
      <Button variant="secondary" disabled={busy || loading || !org} onClick={() => void load()}>Обновить очередь</Button>
    </div>
    {loading && <p role="status">Загрузка очереди…</p>}
    {!loading && !candidates.length && <p className="rounded border border-line p-3 text-sm text-muted">Банковских строк пока нет.</p>}
    {!!candidates.length && <div className="overflow-x-auto rounded border border-line"><table className="w-full text-left text-sm"><thead><tr className="border-b border-line text-muted"><th className="p-2">Дата / источник</th><th className="p-2">Плательщик и назначение</th><th className="p-2">Сумма</th><th className="p-2">Состояние</th><th className="p-2" /></tr></thead><tbody>{candidates.map((candidate) => {
      const source = candidate.source_snapshot;
      const eligible = source.currency === "BYN" && !!source.occurred_on && Number(source.amount) > 0;
      const state = candidate.imported ? `Проведено · № ${candidate.entry_id}` : candidate.binding_status === "own" ? "Привязано к юрлицу" : candidate.binding_status === "other" ? "Привязано к другому юрлицу" : "Нужна привязка";
      return <tr key={source.transaction_id} className="border-b border-line last:border-0"><td className="p-2 align-top"><strong>{source.occurred_on || "Без даты"}</strong><br /><span className="text-xs text-muted">{source.ext_id}</span></td><td className="p-2 align-top">{source.payer_name || source.payer_unp || "Плательщик не указан"}<br /><span className="text-xs text-muted">{source.purpose || "Назначение не указано"}</span></td><td className="p-2 align-top whitespace-nowrap">{source.amount ?? "Некорректная сумма"} {source.currency}</td><td className="p-2 align-top"><span className={candidate.imported ? "text-money" : candidate.binding_status === "own" ? "text-accent-ink" : "text-muted"}>{state}</span>{!eligible && <><br /><span className="text-xs text-red-700">Нужны положительная сумма, дата и BYN.</span></>}</td><td className="p-2 align-top text-right"><div className="flex flex-wrap justify-end gap-2">{candidate.imported && Number.isSafeInteger(candidate.entry_id) && candidate.entry_id! > 0 && onEntry && <Button variant="secondary" disabled={busy} onClick={() => onEntry(candidate.entry_id!)}>Открыть проводку</Button>}{candidate.binding_status === "unbound" && <Button variant="secondary" disabled={busy} onClick={() => void bind(candidate)}>Привязать</Button>}{candidate.binding_status === "own" && !candidate.imported && eligible && <Button disabled={busy} onClick={() => select(candidate)}>Выбрать</Button>}</div></td></tr>;
    })}</tbody></table></div>}
    {selected && !selected.imported && <div className="space-y-3 rounded-xl border border-accent p-3"><h3 className="font-semibold">Проведение строки {selected.source_snapshot.ext_id}</h3><p className="text-sm text-muted">Источник: {selected.source_snapshot.amount} {selected.source_snapshot.currency} · {selected.source_snapshot.purpose || "назначение не указано"}</p><div className="grid gap-3 md:grid-cols-4"><label>Денежный счёт<Select aria-label="Счёт банка импорта" value={bankAccount} disabled={busy || !!preview} onChange={(event) => { setBankAccount(event.target.value); setBankDimensions({}); setPreview(null); setPrepared(null); }}><option value="">Выберите счёт</option>{cashAccounts.map((account) => <option key={account.code} value={account.code}>{account.code} · {account.title}</option>)}</Select></label><label>Счёт расчётов<Select aria-label="Счёт расчётов импорта" value={settlementAccount} disabled={busy || !!preview} onChange={(event) => { setSettlementAccount(event.target.value); setSettlementDimensions({}); setPreview(null); setPrepared(null); }}><option value="">Выберите счёт</option>{settlementAccounts.map((account) => <option key={account.code} value={account.code}>{account.code} · {account.title}</option>)}</Select></label><label>Вид денежного потока<Select aria-label="Поток импорта" value={cashActivity} disabled={busy || !!preview} onChange={(event) => { setCashActivity(event.target.value); setPreview(null); setPrepared(null); }}><option value="operating">Текущая деятельность</option><option value="investing">Инвестиционная</option><option value="financing">Финансовая</option></Select></label><label className="md:col-span-1">Основание<Input aria-label="Основание импорта" value={explanation} disabled={busy || !!preview} onChange={(event) => { setExplanation(event.target.value); setPreview(null); setPrepared(null); }} /></label></div>{([{ code: bankAccount, title: "Банк", values: bankDimensions, update: setBankDimensions }, { code: settlementAccount, title: "Расчёты", values: settlementDimensions, update: setSettlementDimensions }]).map(({ code, title, values, update }) => <div key={title} className="grid gap-3 md:grid-cols-3">{accounts.find((account) => account.code === code)?.required_dimensions.filter((key) => title !== "Банк" || !["bank_statement", "bank_transaction_id"].includes(key)).map((key) => <label key={key}>{title}: {({ counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", department: "Подразделение" } as Record<string, string>)[key] || key}<Input aria-label={`${title}: ${key}`} value={values[key] || ""} disabled={busy || !!preview} onChange={(event) => { update({ ...values, [key]: event.target.value }); setPreview(null); setPrepared(null); }} /></label>)}</div>)}<Button disabled={busy || !policyId || !bankAccount || !settlementAccount || !explanation} onClick={() => void execute(false)}>Рассчитать проводки</Button>{preview && <div className="space-y-2 rounded-xl border border-accent p-3"><p className="text-sm">Источник подтверждён: {preview.source_snapshot.ext_id} · {preview.source_snapshot.amount} BYN</p>{preview.lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN{Object.entries(line.dimensions ?? {}).map(([key, value]) => <span key={key} className="ml-3 text-muted">{key}: {value}</span>)}</p>)}{!preview.normative_verified && <p className="text-red-700">Политика не подтверждена нормативно: подтверждение заблокировано.</p>}<Button disabled={busy || !preview.confirmation_available} onClick={() => void execute(true)}>Подтвердить импорт</Button></div>}</div>}
  </section>;
}
