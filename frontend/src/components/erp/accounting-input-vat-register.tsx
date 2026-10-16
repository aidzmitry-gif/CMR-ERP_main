"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

export type InputVatRegisterRow = {
  entry_id: number;
  line_id: number;
  entry_digest: string;
  posting_date: string;
  side: string;
  amount: string;
  currency: string;
  source: string;
  source_version: number;
  registered?: boolean;
  register_id?: number | null;
  register_tax_period?: string | null;
  register_eschf_status?: string | null;
  register_eschf_identifier?: string | null;
  deduction_status: string;
};

type Props = { org: string; start: string; row: InputVatRegisterRow; onRegistered: () => void };
type Preview = { digest: string; status: string; register_available: boolean; statutory_certified: false; deduction_assessed: false };
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;

export function AccountingInputVatRegister({ org, start, row, onRegistered }: Props) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [invoice, setInvoice] = useState(""), [taxPeriod, setTaxPeriod] = useState(row.register_tax_period || start.slice(0, 7));
  const [eschfStatus, setEschfStatus] = useState("pending"), [eschf, setEschf] = useState("");
  const [deduction, setDeduction] = useState("not_assessed"), [basis, setBasis] = useState(""), [evidence, setEvidence] = useState("");
  const [key, setKey] = useState(requestKey), [preview, setPreview] = useState<Preview | null>(null);
  const disabled = busy || !!row.registered;
  function reset(clearNotice = true) {
    setOpen(false); setPreview(null); setError(""); if (clearNotice) setNotice(""); setKey(requestKey());
  }
  function command() {
    return { request_key: key, entry_id: row.entry_id, line_id: row.line_id, expected_entry_digest: row.entry_digest,
      tax_period: taxPeriod.trim(), invoice_reference: invoice.trim(), eschf_identifier: eschfStatus === "provided" ? eschf.trim() : null,
      deduction_status: deduction, eschf_status: eschfStatus, right_basis: basis.trim(), evidence: evidence.trim() };
  }
  async function inspect() {
    const body = command();
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(body.tax_period) || !body.invoice_reference || body.right_basis.length < 10 || body.evidence.length < 10
      || (body.eschf_status === "provided" && !body.eschf_identifier) || (body.deduction_status === "eligible" && !["provided", "not_required"].includes(body.eschf_status))) {
      setError("Укажите период, документ, основание и подтверждение; для права на вычет нужен явный статус ЭСЧФ."); return;
    }
    setBusy(true); setError(""); setNotice(""); setPreview(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/input-vat-register/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Регистрация входного НДС не подготовлена.");
      if (String(data.organization_id) !== org || data.source?.entry_id !== row.entry_id || data.source?.line_id !== row.line_id
        || data.status !== "reviewed_input_vat" || data.register_available !== true || data.statutory_certified !== false
        || data.deduction_assessed !== false || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest))
        throw new Error("Ответ проверки не соответствует выбранной строке НДС.");
      setPreview(data as Preview); setNotice("Пакет регистрации проверен. Запись ещё не сохранена.");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось проверить регистрацию НДС."); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview || busy) return;
    setBusy(true); setError(""); setNotice("");
    const body = { ...command(), digest: preview.digest };
    try {
      const accessResponse = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
      const access = await accessResponse.json();
      if (!accessResponse.ok || String(access?.organization_id) !== org || typeof access.principal !== "string" || access.can_confirm !== true)
        throw new Error("Нет права подтверждать реестр входного НДС.");
      const response = await fetch(`/api/accounting/organizations/${org}/input-vat-register/confirm`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal }, cache: "no-store", body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) {
        const recovery = await fetch(`/api/accounting/organizations/${org}/input-vat-register/${encodeURIComponent(key)}`, { cache: "no-store" });
        if (recovery.ok) { onRegistered(); reset(false); setNotice("Регистрация уже сохранена. Ведомость обновлена."); return; }
        throw new Error(typeof data.detail === "string" ? data.detail : "Реестр входного НДС не сохранён.");
      }
      if (String(data.organization_id) !== org || data.entry_id !== row.entry_id || data.line_id !== row.line_id || data.digest !== preview.digest || data.statutory_certified !== false || data.deduction_assessed !== false)
        throw new Error("Ответ сохранения реестра не соответствует выбранной строке.");
      onRegistered(); reset(false); setNotice("Запись реестра сохранена. Право на вычет не считается подтверждённым автоматически.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Регистрация НДС не сохранена. Проверьте статус и повторите.");
    } finally { setBusy(false); }
  }
  if (row.registered) return <p className="mt-2 text-sm text-money">Реестр: {row.deduction_status} · ЭСЧФ: {row.register_eschf_status || "не указан"}{row.register_eschf_identifier ? ` · ${row.register_eschf_identifier}` : ""}. Статус не является налоговой сертификацией.</p>;
  return <div className="mt-3 space-y-2">
    {notice && <p role="status">{notice}</p>}
    {!open && <Button variant="secondary" disabled={disabled} onClick={() => { setOpen(true); setError(""); }}>Записать в реестр НДС</Button>}
    {open && <section className="space-y-2 rounded border border-line bg-surface p-3" aria-label={`Регистрация НДС строки ${row.line_id}`}>
      <p className="text-sm text-muted">Сумма {row.amount} {row.currency}; укажите основания вручную. Оплата и статус сделки здесь не определяют право на вычет.</p>
      <div className="grid gap-2 md:grid-cols-2"><Input aria-label="Период реестра НДС" type="month" value={taxPeriod} disabled={disabled || !!preview} onChange={e => setTaxPeriod(e.target.value)} /><Input aria-label="Документ входного НДС" value={invoice} disabled={disabled || !!preview} onChange={e => setInvoice(e.target.value)} placeholder="Номер накладной / счёта-фактуры" />
        <Select aria-label="Статус ЭСЧФ" value={eschfStatus} disabled={disabled || !!preview} onChange={e => setEschfStatus(e.target.value)}><option value="pending">Ожидает проверки</option><option value="provided">Предоставлен</option><option value="not_required">Не требуется</option><option value="not_provided">Не предоставлен</option></Select>
        <Input aria-label="Идентификатор ЭСЧФ" value={eschf} disabled={disabled || !!preview || eschfStatus !== "provided"} onChange={e => setEschf(e.target.value)} placeholder="Только при статусе «предоставлен»" />
        <Select aria-label="Статус права на вычет" value={deduction} disabled={disabled || !!preview} onChange={e => setDeduction(e.target.value)}><option value="not_assessed">Не оценено</option><option value="pending">Ожидает проверки</option><option value="eligible">Допустимо по проверенному основанию</option><option value="not_eligible">Не допускается</option></Select>
        <Input aria-label="Основание права на вычет" value={basis} disabled={disabled || !!preview} onChange={e => setBasis(e.target.value)} placeholder="Политика и первичные документы" /></div>
      <Input aria-label="Подтверждение регистрации НДС" value={evidence} disabled={disabled || !!preview} onChange={e => setEvidence(e.target.value)} placeholder="Что проверил бухгалтер и где хранится подтверждение" />
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={disabled || !!preview} onClick={() => void inspect()}>Проверить пакет</Button>{preview && <Button disabled={disabled} onClick={() => void confirm()}>Сохранить запись реестра</Button>}<Button variant="ghost" disabled={busy} onClick={() => reset()}>Отмена</Button></div>
      {preview && <p className="text-sm text-muted">Пакет {preview.digest.slice(0, 12)}… проверен. Это регистр доказательств; вычет и отчётность не формируются.</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
    </section>}
  </div>;
}
