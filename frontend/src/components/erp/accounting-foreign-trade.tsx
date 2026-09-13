"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

type TradeRow = {
  entry_id: number;
  line_id: number;
  source: string;
  source_version: number;
  operation: string;
  posting_date: string;
  document_date: string;
  operation_date: string;
  side: "debit" | "credit";
  amount: string;
  currency: string;
  original_amount: string | null;
  rate: string | null;
  rate_scale: number | null;
  rate_date: string | null;
  rate_source: string | null;
  account_code: string;
  account_title: string;
  dimensions: Record<string, unknown>;
  review_issues: string[];
  trade_mode: "not_assessed" | "eaeu_import" | "third_country_import" | "export";
  register_id: number | null;
  registered: boolean;
  entry_digest: string;
};

type Worksheet = {
  rows: TradeRow[];
  rows_needing_metadata_review: number;
  rows_needing_register_review: number;
  statutory_certified: false;
  trade_treatment_verified: false;
};

type Preview = {
  digest: string;
  status: string;
  register_available: boolean;
  statutory_certified: false;
  trade_treatment_verified: false;
  source: { entry_id: number; line_id: number; account_code: string };
};

const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID()
  : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;

function ForeignTradeRegisterForm({ org, start, row, onRegistered }: { org: string; start: string; row: TradeRow; onRegistered: () => void }) {
  const defaultMode = row.account_code === "90.1" || row.account_code.startsWith("90.1.") ? "export" : "eaeu_import";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tradeMode, setTradeMode] = useState(defaultMode);
  const [partnerCountry, setPartnerCountry] = useState("");
  const [contract, setContract] = useState("");
  const [invoice, setInvoice] = useState("");
  const [customsReference, setCustomsReference] = useState("");
  const [eaeuReference, setEaeuReference] = useState("");
  const [incoterms, setIncoterms] = useState(defaultMode === "export" ? "" : "DAP");
  const [originalAmount, setOriginalAmount] = useState(row.original_amount ?? "");
  const [rate, setRate] = useState(row.rate ?? "");
  const [rateScale, setRateScale] = useState(row.rate_scale ? String(row.rate_scale) : "");
  const [rateDate, setRateDate] = useState(row.rate_date ?? "");
  const [rateSource, setRateSource] = useState(row.rate_source ?? "");
  const [customsDuty, setCustomsDuty] = useState("0.00");
  const [importVat, setImportVat] = useState("0.00");
  const [exportEvidence, setExportEvidence] = useState("");
  const [evidence, setEvidence] = useState("");
  const [key, setKey] = useState(requestKey);
  const [preview, setPreview] = useState<Preview | null>(null);

  const isImport = tradeMode !== "export";
  const blocked = busy || Boolean(row.registered) || row.review_issues.length > 0;
  function command() {
    const foreign = row.currency !== "BYN";
    return {
      request_key: key, entry_id: row.entry_id, line_id: row.line_id, expected_entry_digest: row.entry_digest,
      tax_period: start.slice(0, 7), trade_mode: tradeMode, partner_country: partnerCountry.trim(),
      contract_reference: contract.trim(), invoice_reference: invoice.trim(),
      customs_reference: customsReference.trim() || null, eaeu_reference: eaeuReference.trim() || null,
      incoterms: incoterms.trim() || null, currency: row.currency,
      original_amount: foreign ? originalAmount.trim() || null : null, rate: foreign ? rate.trim() || null : null,
      rate_scale: foreign && rateScale.trim() ? Number(rateScale) : null,
      rate_date: foreign ? rateDate || null : null, rate_source: foreign ? rateSource.trim() || null : null,
      customs_duty: customsDuty.trim() || "0", import_vat: importVat.trim() || "0",
      export_evidence: tradeMode === "export" ? exportEvidence.trim() || null : null, evidence: evidence.trim(),
    };
  }
  function reset() {
    setOpen(false); setPreview(null); setError(""); setNotice(""); setKey(requestKey());
  }
  async function inspect() {
    const body = command();
    if (!/^[A-Z]{2,64}$/.test(body.partner_country) || !body.contract_reference || !body.invoice_reference
      || body.evidence.length < 10 || (isImport && !body.incoterms)
      || (tradeMode === "eaeu_import" && !body.eaeu_reference)
      || ((tradeMode === "third_country_import" || tradeMode === "export") && !body.customs_reference)
      || (tradeMode === "export" && (!body.export_evidence || body.export_evidence.length < 10))
      || (row.currency !== "BYN" && (!body.original_amount || !body.rate || !body.rate_scale || !body.rate_date || !body.rate_source))) {
      setError("Заполните страну, договор, документ и доказательства. Для импорта укажите Incoterms и документ, для экспорта — таможенное и транспортное подтверждение; валюте нужны курс и источник.");
      return;
    }
    setBusy(true); setError(""); setNotice(""); setPreview(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/foreign-trade-register/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Регистр ВЭД не подготовлен.");
      if (String(data.organization_id) !== org || data.source?.entry_id !== row.entry_id || data.source?.line_id !== row.line_id
        || data.status !== "reviewed_foreign_trade" || data.register_available !== true
        || data.statutory_certified !== false || data.trade_treatment_verified !== false
        || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest)) {
        throw new Error("Ответ проверки не соответствует выбранной строке ВЭД.");
      }
      setPreview(data as Preview); setNotice("Пакет ВЭД проверен. Запись ещё не сохранена.");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось проверить регистр ВЭД."); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const accessResponse = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
      const access = await accessResponse.json();
      if (!accessResponse.ok || String(access?.organization_id) !== org || typeof access.principal !== "string" || access.can_confirm !== true) {
        throw new Error("Нет права подтверждать регистр ВЭД.");
      }
      const response = await fetch(`/api/accounting/organizations/${org}/foreign-trade-register/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal },
        cache: "no-store", body: JSON.stringify({ ...command(), digest: preview.digest }),
      });
      const data = await response.json();
      if (!response.ok) {
        const recovery = await fetch(`/api/accounting/organizations/${org}/foreign-trade-register/${encodeURIComponent(key)}`, { cache: "no-store" });
        if (recovery.ok) { onRegistered(); reset(); setNotice("Запись уже сохранена. Ведомость обновлена."); return; }
        throw new Error(typeof data.detail === "string" ? data.detail : "Регистр ВЭД не сохранён.");
      }
      if (String(data.organization_id) !== org || data.entry_id !== row.entry_id || data.line_id !== row.line_id
        || data.digest !== preview.digest || data.statutory_certified !== false || data.trade_treatment_verified !== false) {
        throw new Error("Ответ сохранения не соответствует выбранной строке ВЭД.");
      }
      onRegistered(); reset(); setNotice("Запись ВЭД сохранена. Таможенная и налоговая сертификация автоматически не выполняется.");
    } catch (e) { setError(e instanceof Error ? e.message : "Регистр ВЭД не сохранён. Проверьте статус и повторите."); }
    finally { setBusy(false); }
  }
  if (row.registered) return <p className="mt-2 text-sm text-money">Регистр ВЭД: {row.trade_mode}. Доказательства сохранены; налоговая сертификация не выполнена.</p>;
  if (row.review_issues.length) return <p className="mt-2 text-sm text-amber-700">Сначала исправьте валютную аналитику источника: {row.review_issues.join(", ")}.</p>;
  return <div className="mt-3 space-y-2">
    {notice && <p role="status">{notice}</p>}
    {!open && <Button variant="secondary" disabled={blocked} onClick={() => { setOpen(true); setError(""); }}>Записать доказательства ВЭД</Button>}
    {open && <section aria-label={`Регистрация ВЭД строки ${row.line_id}`} className="space-y-2 rounded border border-line bg-surface p-3">
      <p className="text-sm text-muted">Сумма источника: {row.amount} {row.currency}. Укажите направление и первичные подтверждения вручную; проводки и налоговая ставка здесь не рассчитываются.</p>
      <div className="grid gap-2 md:grid-cols-2">
        <Select aria-label="Режим ВЭД" value={tradeMode} disabled={busy || !!preview} onChange={e => { setTradeMode(e.target.value); setIncoterms(e.target.value === "export" ? "" : "DAP"); }}><option value="eaeu_import">Импорт ЕАЭС</option><option value="third_country_import">Импорт из третьих стран</option><option value="export">Экспорт</option></Select>
        <Input aria-label="Страна партнёра ВЭД" value={partnerCountry} disabled={busy || !!preview} onChange={e => setPartnerCountry(e.target.value.toUpperCase())} placeholder="KZ" />
        <Input aria-label="Договор ВЭД" value={contract} disabled={busy || !!preview} onChange={e => setContract(e.target.value)} placeholder="Номер договора" />
        <Input aria-label="Документ ВЭД" value={invoice} disabled={busy || !!preview} onChange={e => setInvoice(e.target.value)} placeholder="Инвойс / накладная" />
        {isImport && <Input aria-label="Incoterms" value={incoterms} disabled={busy || !!preview} onChange={e => setIncoterms(e.target.value.toUpperCase())} placeholder="DAP" />}
        {tradeMode === "eaeu_import" && <Input aria-label="Документ ЕАЭС" value={eaeuReference} disabled={busy || !!preview} onChange={e => setEaeuReference(e.target.value)} placeholder="Товаросопроводительный документ" />}
        {(tradeMode === "third_country_import" || tradeMode === "export") && <Input aria-label="Таможенная декларация ВЭД" value={customsReference} disabled={busy || !!preview} onChange={e => setCustomsReference(e.target.value)} placeholder="Номер декларации" />}
        {row.currency !== "BYN" && <><Input aria-label="Иностранная сумма ВЭД" value={originalAmount} disabled={busy || !!preview} onChange={e => setOriginalAmount(e.target.value)} /><Input aria-label="Курс ВЭД" value={rate} disabled={busy || !!preview} onChange={e => setRate(e.target.value)} /><Input aria-label="Масштаб курса ВЭД" value={rateScale} disabled={busy || !!preview} onChange={e => setRateScale(e.target.value)} /><Input aria-label="Дата курса ВЭД" type="date" value={rateDate} disabled={busy || !!preview} onChange={e => setRateDate(e.target.value)} /><Input aria-label="Источник курса ВЭД" value={rateSource} disabled={busy || !!preview} onChange={e => setRateSource(e.target.value)} /></>}
        <Input aria-label="Таможенная пошлина ВЭД" value={customsDuty} disabled={busy || !!preview || tradeMode === "export"} onChange={e => setCustomsDuty(e.target.value)} />
        <Input aria-label="Ввозной НДС ВЭД" value={importVat} disabled={busy || !!preview || tradeMode === "export"} onChange={e => setImportVat(e.target.value)} />
      </div>
      {tradeMode === "export" && <Input aria-label="Подтверждение экспорта ВЭД" value={exportEvidence} disabled={busy || !!preview} onChange={e => setExportEvidence(e.target.value)} placeholder="Таможенные и транспортные документы" />}
      <Input aria-label="Доказательства ВЭД" value={evidence} disabled={busy || !!preview} onChange={e => setEvidence(e.target.value)} placeholder="Что проверил бухгалтер и где хранится подтверждение" />
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={blocked || !!preview} onClick={() => void inspect()}>Проверить пакет ВЭД</Button>{preview && <Button disabled={blocked} onClick={() => void confirm()}>Сохранить запись ВЭД</Button>}<Button variant="ghost" disabled={busy} onClick={reset}>Отмена</Button></div>
      {preview && <p className="text-sm text-muted">Пакет {preview.digest.slice(0, 12)}… проверен. Он фиксирует доказательства, но не формирует проводки.</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
    </section>}
  </div>;
}

export function AccountingForeignTrade({ org, start, end, onEntry }: { org: string; start: string; end: string; onEntry: (id: number) => void }) {
  const [reload, setReload] = useState(0);
  const [registrationNotice, setRegistrationNotice] = useState("");
  const [result, setResult] = useState<{ key: string; data?: Worksheet; error?: boolean } | null>(null);
  const valid = Boolean(org && start && end && start <= end);
  const key = `${org}/${start}/${end}/${reload}`;
  useEffect(() => {
    if (!valid) return;
    let active = true;
    const controller = new AbortController();
    fetch(`/api/accounting/organizations/${org}/foreign-trade-lines?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, { cache: "no-store", signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error("Unable to load worksheet");
      const data = await response.json();
      if (active) setResult({ key, data });
    }).catch(() => { if (active) setResult({ key, error: true }); });
    return () => { active = false; controller.abort(); };
  }, [org, start, end, valid, key]);
  const current = result?.key === key ? result : null;
  return <section aria-label="Ведомость ВЭД" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">ВЭД — импорт и экспорт</h2><Button variant="secondary" disabled={!valid} onClick={() => { setRegistrationNotice(""); setReload(value => value + 1); }}>Обновить ведомость ВЭД</Button></div>
    {registrationNotice && <p role="status">{registrationNotice}</p>}
    <p className="text-sm text-muted">Кандидаты выбираются из уже проведённых строк запасов, входного НДС и выручки. Регистр хранит документы и курс, но не объявляет ставку, вычет, таможенную стоимость или себестоимость подтверждёнными автоматически.</p>
    {!org ? <p>Выберите юрлицо.</p> : !valid ? <p role="alert">Укажите корректный период.</p> : !current ? <p role="status">Загрузка ведомости ВЭД…</p> : current.error ? <p role="alert">Не удалось загрузить ведомость ВЭД. Проверьте доступ и повторите загрузку.</p> : current.data && <>
      <p>Строк с неполным валютным источником: {current.data.rows_needing_metadata_review}. Без записи доказательств: {current.data.rows_needing_register_review}.</p>
      {current.data.rows.map(row => <article key={row.line_id} className="rounded border border-line p-3">
        <button type="button" className="text-accent underline" onClick={() => onEntry(row.entry_id)}>Операция № {row.entry_id} · {row.source}</button>
        <p>{row.posting_date} · {row.side === "debit" ? "Дт" : "Кт"} {row.account_code} · {row.amount} {row.currency} · источник v{row.source_version}</p>
        <p className="text-sm">{row.account_title} · {row.operation} · Документ операции: {row.document_date}</p>
        <ForeignTradeRegisterForm org={org} start={start} row={row} onRegistered={() => { setRegistrationNotice("Запись ВЭД сохранена. Ведомость обновляется."); setReload(value => value + 1); }} />
      </article>)}
      {!current.data.rows.length && <p>Кандидатов ВЭД за выбранный период нет.</p>}
    </>}
  </section>;
}
