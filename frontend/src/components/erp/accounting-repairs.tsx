"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/input";

type RepairRow = { entry_id: number; service_request_id: number; month: string; serial_number: string; owner_type: string; owner_reference: string; coverage: string; financial_result: { service_amount_byn: string; cost_amount_byn: string; gross_result_byn: string; customer_material_lines: string[] }; digest: string };
type Props = { org: string; month: string; policyId: string; onEntry: (id: number) => void; disabled?: boolean };
type Preview = { digest: string; status: string; posting_available: boolean; financial_result: RepairRow["financial_result"]; statutory_certified?: false; final_cost_certified?: false };
type RepairCostDraft = { kind: "material" | "labor" | "external"; material_owner: "own" | "customer"; description: string; amount_byn: string; debit_account: string; credit_account: string; evidence: string };
const requestKey = () => typeof crypto !== "undefined" && typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `00000000-0000-4000-8000-${Date.now().toString().padStart(12, "0")}`;
const emptyCostLine = (): RepairCostDraft => ({ kind: "material", material_owner: "own", description: "Материалы ремонта", amount_byn: "", debit_account: "90.2", credit_account: "10.1", evidence: "" });

export function AccountingRepairs({ org, month, policyId, onEntry, disabled = false }: Props) {
  const [rows, setRows] = useState<RepairRow[]>([]), [rowsOrg, setRowsOrg] = useState(""), [reload, setReload] = useState(0);
  const [requestId, setRequestId] = useState(requestKey), [serviceRequest, setServiceRequest] = useState(""), [sourceDocument, setSourceDocument] = useState("service-request:"), [sourceDigest, setSourceDigest] = useState("");
  const [serial, setSerial] = useState(""), [ownerType, setOwnerType] = useState("customer"), [ownerReference, setOwnerReference] = useState(""), [coverage, setCoverage] = useState("paid"), [counterparty, setCounterparty] = useState("");
  const [serviceAmount, setServiceAmount] = useState(""), [settlementAccount, setSettlementAccount] = useState("62"), [revenueAccount, setRevenueAccount] = useState("90.1");
  const [costLines, setCostLines] = useState<RepairCostDraft[]>([emptyCostLine()]);
  const [customerMaterial, setCustomerMaterial] = useState(false), [evidence, setEvidence] = useState(""), [preview, setPreview] = useState<Preview | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!org) return;
    let active = true;
    fetch(`/api/accounting/organizations/${org}/repairs?month=${encodeURIComponent(month)}`, { cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error("Не удалось загрузить реестр ремонтов.");
      const data = await response.json();
      if (active) { setRows(Array.isArray(data.rows) ? data.rows : []); setRowsOrg(org); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "Не удалось загрузить реестр ремонтов."); });
    return () => { active = false; };
  }, [org, month, reload]);

  function updateCostLine(index: number, patch: Partial<RepairCostDraft>) {
    setCostLines(lines => lines.map((line, current) => current === index ? { ...line, ...patch } : line));
  }

  function toggleFirstCustomerMaterial(checked: boolean) {
    setCustomerMaterial(checked);
    setCostLines(lines => lines.map((line, index) => index === 0
      ? { ...line, material_owner: checked ? "customer" : "own", amount_byn: checked ? "0.00" : "", debit_account: checked ? "" : line.debit_account, credit_account: checked ? "" : line.credit_account, description: checked ? "Материал клиента" : "Материалы ремонта" }
      : line));
  }

  function command(extra: Record<string, unknown> = {}) {
    const lines = costLines.map((line, index) => {
      const customer = index === 0 ? customerMaterial : line.material_owner === "customer";
      if (customer) return { source_line_id: `customer-material-${index + 1}`, kind: line.kind, material_owner: "customer", description: line.description.trim() || "Материал клиента", amount_byn: "0.00", evidence: line.evidence.trim() || evidence.trim() || "Акт передачи имущества клиента без оприходования" };
      return { source_line_id: `repair-cost-${index + 1}`, kind: line.kind, material_owner: "own", description: line.description.trim(), amount_byn: line.amount_byn.trim(), debit_account: line.debit_account.trim(), credit_account: line.credit_account.trim(), dimensions: {}, evidence: line.evidence.trim() || evidence.trim() };
    });
    return { request_key: requestId, service_request_id: Number(serviceRequest), source_document: sourceDocument.trim(), source_version: 1, source_digest: sourceDigest.trim(), serial_number: serial.trim(), owner_type: ownerType, owner_reference: ownerReference.trim(), coverage, counterparty_reference: coverage === "paid" ? counterparty.trim() : undefined, policy_id: Number(policyId), posting_date: `${month}-01`, service_amount_byn: coverage === "paid" ? serviceAmount.trim() : "0.00", settlement_account: coverage === "paid" ? settlementAccount.trim() : undefined, revenue_account: coverage === "paid" ? revenueAccount.trim() : undefined, source_evidence: evidence.trim(), lines, ...extra };
  }

  async function inspect() {
    const body = command();
    const submittedLines = body.lines as Array<Record<string, unknown>>;
    const invalidOwnLine = submittedLines.some(line => line.material_owner === "own" && (!/^\d+\.\d{2}$/.test(String(line.amount_byn)) || String(line.evidence ?? "").trim().length < 10 || !String(line.debit_account ?? "").trim() || !String(line.credit_account ?? "").trim()));
    const invalidCustomerLine = submittedLines.some(line => line.material_owner === "customer" && (String(line.amount_byn) !== "0.00" || String(line.evidence ?? "").trim().length < 10));
    if (!Number.isInteger(body.service_request_id) || body.service_request_id <= 0 || !body.source_document || !/^[a-f0-9]{64}$/.test(body.source_digest) || !body.serial_number || !body.owner_reference || !body.policy_id || (coverage === "paid" && (!/^\d+\.\d{2}$/.test(body.service_amount_byn as string) || !counterparty.trim())) || !submittedLines.length || invalidOwnLine || invalidCustomerLine || evidence.trim().length < 10) { setError("Укажите заявку, digest, серийный номер, владельца, суммы и подтверждающее основание для каждой строки."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/repair-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Ремонт не подготовлен.");
      if (String(data.organization_id) !== org || data.status !== "reviewed_repair" || data.posting_available !== true || typeof data.digest !== "string") throw new Error("Ответ проверки ремонта не соответствует источнику.");
      setPreview(data as Preview); setNotice("Пакет ремонта проверен. Проводка ещё не создана.");
    } catch (e) { setError(e instanceof Error ? e.message : "Ремонт не подготовлен."); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview || busy) return;
    setBusy(true); setError("");
    try {
      const accessResponse = await fetch(`/api/accounting/organizations/${org}/production-overhead-access`, { cache: "no-store" });
      const access = await accessResponse.json();
      if (!accessResponse.ok || String(access?.organization_id) !== org || typeof access.principal !== "string" || access.can_confirm !== true) throw new Error("Нет права проводить ремонт.");
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/repair-confirm`, { method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": access.principal }, cache: "no-store", body: JSON.stringify(command({ digest: preview.digest })) });
      const data = await response.json();
      if (!response.ok) {
        const recovery = await fetch(`/api/accounting/organizations/${org}/repairs/${encodeURIComponent(requestId)}`, { cache: "no-store" });
        if (recovery.ok) { setNotice("Ремонт уже проведён. Результат восстановлен."); setPreview(null); return; }
        throw new Error(typeof data.detail === "string" ? data.detail : "Ремонт не проведён.");
      }
      if (String(data.organization_id) !== org || data.digest !== preview.digest) throw new Error("Ответ проведения ремонта не соответствует пакету.");
      setNotice(`Ремонт проведён, операция № ${data.entry_id}.`); setPreview(null); setRequestId(requestKey()); setReload(value => value + 1); onEntry(data.entry_id);
    } catch (e) { setError(e instanceof Error ? e.message : "Ремонт не проведён."); }
    finally { setBusy(false); }
  }

  const visibleRows = rowsOrg === org ? rows : [];
  return <section aria-label="Ремонты" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Платные и гарантийные ремонты</h2><Button variant="secondary" disabled={disabled || busy || !org} onClick={() => setReload(value => value + 1)}>Обновить реестр</Button></div>
    <p className="text-sm text-muted">Серийный номер, владелец и покрытие обязательны. Имущество клиента фиксируется в основании с нулевой бухгалтерской стоимостью и не списывается со склада.</p>
    <section className="space-y-2 rounded border border-line p-3"><h3 className="font-semibold">Подготовить ремонт</h3>
      <div className="grid gap-2 md:grid-cols-3"><Input aria-label="Заявка ремонта" value={serviceRequest} disabled={disabled || busy || !!preview} onChange={e => setServiceRequest(e.target.value)} placeholder="ID заявки" /><Input aria-label="Документ ремонта" value={sourceDocument} disabled={disabled || busy || !!preview} onChange={e => setSourceDocument(e.target.value)} /><Input aria-label="Digest источника ремонта" value={sourceDigest} disabled={disabled || busy || !!preview} onChange={e => setSourceDigest(e.target.value)} placeholder="SHA-256" /><Input aria-label="Серийный номер ремонта" value={serial} disabled={disabled || busy || !!preview} onChange={e => setSerial(e.target.value)} /><Select aria-label="Владелец изделия" value={ownerType} disabled={disabled || busy || !!preview} onChange={e => setOwnerType(e.target.value)}><option value="customer">Клиент</option><option value="organization">Организация</option></Select><Input aria-label="Код владельца изделия" value={ownerReference} disabled={disabled || busy || !!preview} onChange={e => setOwnerReference(e.target.value)} placeholder="ID/код владельца" /><Select aria-label="Покрытие ремонта" value={coverage} disabled={disabled || busy || !!preview} onChange={e => setCoverage(e.target.value)}><option value="paid">Платный</option><option value="warranty">Гарантийный</option></Select><Input aria-label="Контрагент ремонта" value={counterparty} disabled={disabled || busy || !!preview || coverage === "warranty"} onChange={e => setCounterparty(e.target.value)} /><Input aria-label="Стоимость услуги ремонта" value={serviceAmount} disabled={disabled || busy || !!preview || coverage === "warranty"} onChange={e => setServiceAmount(e.target.value)} placeholder="0.00 BYN" /><Input aria-label="Счёт расчётов ремонта" value={settlementAccount} disabled={disabled || busy || !!preview || coverage === "warranty"} onChange={e => setSettlementAccount(e.target.value)} /><Input aria-label="Счёт выручки ремонта" value={revenueAccount} disabled={disabled || busy || !!preview || coverage === "warranty"} onChange={e => setRevenueAccount(e.target.value)} /><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={customerMaterial} disabled={disabled || busy || !!preview} onChange={e => toggleFirstCustomerMaterial(e.target.checked)} />Материал клиента</label><Input aria-label="Стоимость собственных материалов ремонта" value={costLines[0]?.amount_byn ?? ""} disabled={disabled || busy || !!preview || customerMaterial} onChange={e => updateCostLine(0, { amount_byn: e.target.value })} placeholder="0.00 BYN" /><Input aria-label="Дебет затрат ремонта" value={costLines[0]?.debit_account ?? ""} disabled={disabled || busy || !!preview || customerMaterial} onChange={e => updateCostLine(0, { debit_account: e.target.value })} /><Input aria-label="Кредит материалов ремонта" value={costLines[0]?.credit_account ?? ""} disabled={disabled || busy || !!preview || customerMaterial} onChange={e => updateCostLine(0, { credit_account: e.target.value })} /><Input aria-label="Основание ремонта" value={evidence} disabled={disabled || busy || !!preview} onChange={e => setEvidence(e.target.value)} placeholder="Акт ремонта и подтверждение владельца" /></div>
      <div className="space-y-2">{costLines.slice(1).map((line, index) => { const lineIndex = index + 1; const customer = line.material_owner === "customer"; return <fieldset key={lineIndex} className="grid gap-2 rounded border border-line p-3 md:grid-cols-4"><legend className="text-sm">Строка затрат {lineIndex + 1}</legend><Select aria-label={`Тип затрат ремонта ${lineIndex + 1}`} value={line.kind} disabled={disabled || busy || !!preview} onChange={e => updateCostLine(lineIndex, { kind: e.target.value as RepairCostDraft["kind"] })}><option value="material">Материал</option><option value="labor">Труд</option><option value="external">Внешняя работа</option></Select><Select aria-label={`Принадлежность строки ремонта ${lineIndex + 1}`} value={line.material_owner} disabled={disabled || busy || !!preview} onChange={e => updateCostLine(lineIndex, { material_owner: e.target.value as RepairCostDraft["material_owner"], amount_byn: e.target.value === "customer" ? "0.00" : "", debit_account: e.target.value === "customer" ? "" : "90.2", credit_account: e.target.value === "customer" ? "" : "10.1" })}><option value="own">Собственная</option><option value="customer">Клиента</option></Select><Input aria-label={`Описание затрат ремонта ${lineIndex + 1}`} value={line.description} disabled={disabled || busy || !!preview} onChange={e => updateCostLine(lineIndex, { description: e.target.value })} /><Input aria-label={`Стоимость строки ремонта ${lineIndex + 1}`} value={line.amount_byn} disabled={disabled || busy || !!preview || customer} onChange={e => updateCostLine(lineIndex, { amount_byn: e.target.value })} placeholder="0.00 BYN" /><Input aria-label={`Дебет строки ремонта ${lineIndex + 1}`} value={line.debit_account} disabled={disabled || busy || !!preview || customer} onChange={e => updateCostLine(lineIndex, { debit_account: e.target.value })} /><Input aria-label={`Кредит строки ремонта ${lineIndex + 1}`} value={line.credit_account} disabled={disabled || busy || !!preview || customer} onChange={e => updateCostLine(lineIndex, { credit_account: e.target.value })} /><Input aria-label={`Основание строки ремонта ${lineIndex + 1}`} value={line.evidence} disabled={disabled || busy || !!preview} onChange={e => updateCostLine(lineIndex, { evidence: e.target.value })} placeholder="Основание строки" /><Button variant="secondary" disabled={disabled || busy || !!preview} onClick={() => setCostLines(lines => lines.filter((_, current) => current !== lineIndex))}>Удалить строку затрат {lineIndex + 1}</Button></fieldset>; })}</div>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={disabled || busy || !!preview || costLines.length >= 20} onClick={() => setCostLines(lines => [...lines, emptyCostLine()])}>Добавить строку затрат</Button></div>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={disabled || busy || !!preview} onClick={() => void inspect()}>Проверить ремонт</Button>{preview && <Button disabled={disabled || busy} onClick={() => void confirm()}>Провести ремонт</Button>}</div>
      {preview && <p className="text-sm text-muted">Результат: выручка {preview.financial_result.service_amount_byn} BYN · затраты {preview.financial_result.cost_amount_byn} BYN · итог {preview.financial_result.gross_result_byn} BYN.</p>}
    </section>
    {visibleRows.map(row => <article key={row.entry_id} className="rounded border border-line p-3 text-sm"><button className="text-accent underline" onClick={() => onEntry(row.entry_id)}>Операция № {row.entry_id}</button><p>{row.coverage === "paid" ? "Платный" : "Гарантийный"} · заявка {row.service_request_id} · {row.serial_number}</p><p className="text-muted">Итог: {row.financial_result.gross_result_byn} BYN · владелец: {row.owner_reference}</p></article>)}
    {rowsOrg === org && !visibleRows.length && <p className="text-muted">Проведённых ремонтов за период нет.</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}
