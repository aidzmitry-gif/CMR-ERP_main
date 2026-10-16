"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";

export type OutputVatRegisterRow = {
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
  tax_treatment: string;
  review_issues?: string[];
};

type Props = { org: string; start: string; row: OutputVatRegisterRow; onRegistered: () => void; disabled?: boolean };
type Preview = { digest: string; status: string; register_available: boolean; statutory_certified: false; vat_treatment_verified: false };
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;

export function AccountingOutputVatRegister({ org, start, row, onRegistered, disabled = false }: Props) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [invoice, setInvoice] = useState(""), [taxPeriod, setTaxPeriod] = useState(row.register_tax_period || start.slice(0, 7));
  const [treatment, setTreatment] = useState("not_assessed"), [eschfStatus, setEschfStatus] = useState("pending"), [eschf, setEschf] = useState("");
  const [basis, setBasis] = useState(""), [exportEvidence, setExportEvidence] = useState(""), [evidence, setEvidence] = useState("");
  const [key, setKey] = useState(requestKey), [preview, setPreview] = useState<Preview | null>(null);
  const blocked = disabled || busy || !!row.registered || (row.review_issues?.length ?? 0) > 0;
  function reset(clearNotice = true) {
    setOpen(false); setPreview(null); setError(""); if (clearNotice) setNotice(""); setKey(requestKey());
  }
  function command() {
    return { request_key: key, entry_id: row.entry_id, line_id: row.line_id, expected_entry_digest: row.entry_digest,
      tax_period: taxPeriod.trim(), invoice_reference: invoice.trim(), tax_treatment: treatment,
      eschf_identifier: eschfStatus === "provided" ? eschf.trim() : null, eschf_status: eschfStatus,
      treatment_basis: basis.trim(), export_evidence: treatment === "zero_export" ? exportEvidence.trim() : null,
      evidence: evidence.trim() };
  }
  async function inspect() {
    const body = command();
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(body.tax_period) || !body.invoice_reference || body.tax_treatment === "not_assessed"
      || body.treatment_basis.length < 10 || body.evidence.length < 10
      || (body.eschf_status === "provided" && !body.eschf_identifier)
      || (body.tax_treatment === "zero_export" && (!body.export_evidence || body.export_evidence.length < 10))) {
      setError("Укажите период, документ, конкретное налоговое обращение, основание и подтверждение; для нулевой ставки добавьте доказательство экспорта."); return;
    }
    setBusy(true); setError(""); setNotice(""); setPreview(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/output-vat-register/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Регистрация исходящего НДС не подготовлена.");
      if (String(data.organization_id) !== org || data.source?.entry_id !== row.entry_id || data.source?.line_id !== row.line_id
        || data.status !== "reviewed_output_vat" || data.register_available !== true || data.statutory_certified !== false
        || data.vat_treatment_verified !== false || typeof data.digest !== "string" || !/^[a-f0-9]{64}$/.test(data.digest))
        throw new Error("Ответ проверки не соответствует выбранной строке исходящего НДС.");
      setPreview(data as Preview); setNotice("Пакет регистрации проверен. Запись ещё не сохранена.");
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось проверить регистрацию исходящего НДС."); }
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
        throw new Error("Нет права подтверждать реестр исходящего НДС.");
      const response = await fetch(`/api/accounting/organizations/${org}/output-vat-register/confirm`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal }, cache: "no-store", body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) {
        const recovery = await fetch(`/api/accounting/organizations/${org}/output-vat-register/${encodeURIComponent(key)}`, { cache: "no-store" });
        if (recovery.ok) { onRegistered(); reset(false); setNotice("Регистрация уже сохранена. Ведомость обновлена."); return; }
        throw new Error(typeof data.detail === "string" ? data.detail : "Реестр исходящего НДС не сохранён.");
      }
      if (String(data.organization_id) !== org || data.entry_id !== row.entry_id || data.line_id !== row.line_id || data.digest !== preview.digest || data.statutory_certified !== false || data.vat_treatment_verified !== false)
        throw new Error("Ответ сохранения реестра не соответствует выбранной строке исходящего НДС.");
      onRegistered(); reset(false); setNotice("Запись реестра сохранена. Налоговая ставка не считается сертифицированной автоматически.");
    } catch (e) { setError(e instanceof Error ? e.message : "Регистрация исходящего НДС не сохранена. Проверьте статус и повторите."); }
    finally { setBusy(false); }
  }
  if (row.registered) return <p className="mt-2 text-sm text-money">Реестр: {row.tax_treatment} · ЭСЧФ: {row.register_eschf_status || "не указан"}{row.register_eschf_identifier ? ` · ${row.register_eschf_identifier}` : ""}. Статус не является налоговой сертификацией.</p>;
  if (row.review_issues?.length) return <p className="mt-2 text-sm text-amber-700">Строка требует исправления аналитики: {row.review_issues.join(", ")}.</p>;
  return <div className="mt-3 space-y-2">
    {notice && <p role="status">{notice}</p>}
    {!open && <Button variant="secondary" disabled={blocked} onClick={() => { setOpen(true); setError(""); }}>Записать в реестр исходящего НДС</Button>}
    {open && <section className="space-y-2 rounded border border-line bg-surface p-3" aria-label={`Регистрация исходящего НДС строки ${row.line_id}`}>
      <p className="text-sm text-muted">Сумма {row.amount} {row.currency}; укажите основание ставки вручную. Оплата и статус сделки здесь не определяют налоговое обращение.</p>
      <div className="grid gap-2 md:grid-cols-2"><Input aria-label="Период реестра исходящего НДС" type="month" value={taxPeriod} disabled={blocked || !!preview} onChange={e => setTaxPeriod(e.target.value)} /><Input aria-label="Документ исходящего НДС" value={invoice} disabled={blocked || !!preview} onChange={e => setInvoice(e.target.value)} placeholder="Номер счёта / накладной" />
        <Select aria-label="Налоговое обращение" value={treatment} disabled={blocked || !!preview} onChange={e => setTreatment(e.target.value)}><option value="not_assessed">Не оценено</option><option value="pending">Ожидает проверки</option><option value="standard">Обычная ставка</option><option value="zero_export">Нулевая ставка — экспорт</option><option value="exempt">Освобождение</option><option value="not_subject">Не является объектом</option></Select>
        <Select aria-label="Статус ЭСЧФ исходящего НДС" value={eschfStatus} disabled={blocked || !!preview} onChange={e => setEschfStatus(e.target.value)}><option value="pending">Ожидает проверки</option><option value="provided">Предоставлен</option><option value="not_required">Не требуется</option><option value="not_provided">Не предоставлен</option></Select>
        <Input aria-label="Идентификатор ЭСЧФ исходящего НДС" value={eschf} disabled={blocked || !!preview || eschfStatus !== "provided"} onChange={e => setEschf(e.target.value)} placeholder="Только при статусе «предоставлен»" />
        <Input aria-label="Основание налогового обращения" value={basis} disabled={blocked || !!preview} onChange={e => setBasis(e.target.value)} placeholder="Ставка, политика и первичные документы" /></div>
      {treatment === "zero_export" && <Input aria-label="Доказательство экспорта" value={exportEvidence} disabled={blocked || !!preview} onChange={e => setExportEvidence(e.target.value)} placeholder="Таможенные и транспортные подтверждения" />}
      <Input aria-label="Подтверждение регистрации исходящего НДС" value={evidence} disabled={blocked || !!preview} onChange={e => setEvidence(e.target.value)} placeholder="Что проверил бухгалтер и где хранится подтверждение" />
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={blocked || !!preview} onClick={() => void inspect()}>Проверить пакет</Button>{preview && <Button disabled={blocked} onClick={() => void confirm()}>Сохранить запись реестра</Button>}<Button variant="ghost" disabled={busy} onClick={() => reset()}>Отмена</Button></div>
      {preview && <p className="text-sm text-muted">Пакет {preview.digest.slice(0, 12)}… проверен. Это регистр доказательств; проводка и налоговая отчётность не формируются.</p>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
    </section>}
  </div>;
}
