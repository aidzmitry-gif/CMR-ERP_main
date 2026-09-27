"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { canonical, fetchProcurementSkus, fetchProcurementSuppliers, type ProcurementSkuOption, type ProcurementSupplierOption } from "@/lib/procurement-machine";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";
import { ProcurementReceiptPosting, type ReceiptAccount } from "./procurement-receipt-posting";

const item = () => ({ order_id: null as number | null, sku_id: null as number | null, sku_title: null as string | null, sku: "", unit: null as string | null, lot: "", quantity: "", net_amount: "", vat_amount: "", vat_rate: "", vat_basis: "" });
const blank = () => ({ currency: "BYN", invoice_reference: "", document_date: "", operation_date: "", supplier: "", supplier_id: null as number | null, supplier_unp: null as string | null, contract: "", contract_id: null as number | null, contract_basis: null as string | null, warehouse: "", warehouse_id: null as number | null, warehouse_title: null as string | null, explanation: "", items: [item()] });
type Document = ReturnType<typeof blank>;
type ReceiptWarehouseOption = { id: number; name: string; title: string; is_active: true };
type SupplierContract = { id: number; organization_id: number; supplier_id: number; number: string; title: string; signed_on: string; expires_on: string | null; evidence: string; is_active?: boolean; created_by?: string; created_at?: string; deactivated_by?: string | null; deactivated_at?: string | null; deactivation_reason?: string | null };
type ContractHistoryPage = { organization_id: number; supplier_id: number; status: string; items: SupplierContract[]; truncated: boolean; next_before_at: string | null; next_before_id: number | null };
type ContractHistoryCursor = { at: string; id: number };
type Receipt = { id: number; organization_id?: number; key?: string; version: number; status?: string; posting?: { entry_id: number; version: number } | null; correction_of?: { receipt_id: number; version: number; entry_id: number } | null; revisions: { version: number; request_key?: string | null; actor: string; created_at: string; document: Document }[] };
const correctionFlagNames = ["physical_change", "inventory_value_change", "vat_change", "primary_document_change", "operation_date_change", "explanation_only", "no_difference"] as const;
type CorrectionFlag = typeof correctionFlagNames[number];
type CorrectionReadiness = { organization_id: number; receipt_id: number; current_version: number; correction_of: { receipt_id: number; version: number; entry_id: number }; classification: string[]; physical_change: boolean; inventory_value_change: boolean; vat_change: boolean; primary_document_change: boolean; operation_date_change: boolean; explanation_only: boolean; no_difference: boolean; posting_available: false; wms_movement_available: false; blockers: string[] };
type CorrectionReadinessState = { context: string; status: "idle" | "loading" | "ready" | "error"; data?: CorrectionReadiness };
type InboundVatEvidenceKind = "supplier_eschf_xml" | "supporting_document_pdf";
type InboundVatEvidenceFile = { file_id: number; organization_id: number; receipt_id: number; receipt_version: number; kind: InboundVatEvidenceKind; tax_period: string; reference: string; filename: string; content_type: string; size_bytes: number; sha256: string; evidence: string; request_key: string; supersedes_id: number | null; digest: string; actor: string; created_at: string; is_current: boolean; bytes_verified_at_upload: true; signature_verified: false; document_facts_verified: false; posting_available: false };
type InboundVatEvidenceState = { context: string; status: "idle" | "loading" | "ready" | "error"; files?: Record<InboundVatEvidenceKind, InboundVatEvidenceFile[]> };
type InboundVatWorkpaperFlags = { review_only: true; signature_verified: false; document_facts_verified: false; deduction_eligibility_assessed: false; accountant_accepted: false; posting_available: false };
type InboundVatWorkpaperEvidence = { file_id: number; receipt_id: number; receipt_version: number; kind: InboundVatEvidenceKind; tax_period: string; reference: string; filename: string; content_type: string; size_bytes: number; sha256: string; digest: string };
type InboundVatWorkpaperLine = { line_id: number; account_id: number; account_code: string; account_title: string; category: string; cash: boolean; amount: string; currency: string; dimensions: Record<string, unknown> };
type InboundVatWorkpaperSnapshot = InboundVatWorkpaperFlags & { organization_id: number; receipt: { correction_receipt_id: number; correction_version: number; correction_revision_id: number; correction_document_digest: string; original_receipt_id: number; original_version: number; original_revision_id: number; original_document_digest: string; source_entry_id: number; source_entry: string; source_version: number; source_entry_digest: string; source_posting_date: string; source_operation_date: string }; tax_period: string; classification: string[]; source_account_18_lines: InboundVatWorkpaperLine[]; evidence_files: InboundVatWorkpaperEvidence[] };
type InboundVatWorkpaperPreview = InboundVatWorkpaperFlags & { organization_id: number; receipt_id: number; receipt_version: number; original_receipt_id: number; original_version: number; tax_period: string; basis: InboundVatWorkpaperSnapshot; basis_digest: string; status: "review_only_workpaper_ready"; source_account_18_line_count: number; current_evidence_file_count: number; evidence_bytes_verified_at_review: true };
type InboundVatWorkpaperConfirmBody = { request_key: string; receipt_id: number; receipt_version: number; tax_period: string; basis_digest: string; reviewer_evidence: string; supersedes_workpaper_id: number | null };
type InboundVatWorkpaperResult = InboundVatWorkpaperFlags & { workpaper_id: number; organization_id: number; receipt_id: number; receipt_version: number; original_receipt_id: number; original_version: number; source_entry_id: number; source_entry_digest: string; tax_period: string; revision: number; supersedes_workpaper_id: number | null; request_key: string; request_digest: string; basis_digest: string; snapshot_digest: string; reviewer_evidence: string; reviewed_by: string; created_at: string; snapshot: InboundVatWorkpaperSnapshot; status: "review_only_workpaper"; evidence_bytes_verified_at_review: true };
type PendingInboundVatWorkpaper = { organization_id: number; receipt_id: number; receipt_version: number; tax_period: string; request_key: string; body: InboundVatWorkpaperConfirmBody; body_json: string; journal_json: string };
type InboundVatWorkpaperHistoryState = { scope: string; status: "idle" | "loading" | "ready" | "error"; items: InboundVatWorkpaperResult[]; error: string };
type InboundVatWorkpaperPreviewState = { scope: string; evidence_digest: string; status: "idle" | "loading" | "ready" | "error"; data?: InboundVatWorkpaperPreview; error: string };
type InboundVatEvidenceForm = { file: File | null; reference: string; tax_period: string; evidence: string };
const evidenceKinds: { kind: InboundVatEvidenceKind; title: string; accept: string; mime: string[]; extension: string }[] = [
  { kind: "supplier_eschf_xml", title: "Электронный счёт-фактура поставщика (XML)", accept: ".xml,application/xml,text/xml", mime: ["application/xml", "text/xml"], extension: ".xml" },
  { kind: "supporting_document_pdf", title: "Подтверждающий документ (PDF)", accept: ".pdf,application/pdf", mime: ["application/pdf"], extension: ".pdf" },
];
const evidenceMaxBytes = 10 * 1024 * 1024;
const evidenceSha256 = /^[a-f0-9]{64}$/;
const taxPeriodPattern = /^\d{4}-(0[1-9]|1[0-2])$/;
const secureUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const inboundVatWorkpaperFlags = { review_only: true, signature_verified: false, document_facts_verified: false,
  deduction_eligibility_assessed: false, accountant_accepted: false, posting_available: false } as const;
type PendingSave = { org: string; receiptId: number | null; version: number; key: string; document: Document; closeAfterSave: boolean };
type PendingContractRevoke = { org: string; supplierId: number; contractId: number; key: string; reason: string };
type OwnedOrder = { kind: string; source_id: number; snapshot: { number: string; supplier: string } };
const fields = [["invoice_reference", "Номер первичной накладной"], ["document_date", "Дата первичной накладной"], ["operation_date", "Дата поступления"], ["contract", "Договор накладной"], ["explanation", "Содержание накладной"]] as const;
const itemFields = [["lot", "Партия"], ["quantity", "Количество"], ["net_amount", "Стоимость без НДС"], ["vat_rate", "Ставка НДС %"], ["vat_amount", "Сумма НДС"], ["vat_basis", "Основание НДС"]] as const;
const itemHistoryFields = [["order_id", "Заказ поставщику"], ["order_line_id", "Строка заказа"], ["sku_id", "ID номенклатуры"], ["sku_title", "Название номенклатуры"], ["sku", "Код номенклатуры"], ["unit", "Единица измерения"], ...itemFields] as const;
const shown = (value: unknown) => value === null || value === undefined || value === "" ? "—" : String(value);
const saveJournalKey = (org: string) => `procurement-receipt-save:v1:${org}`;
const exactKeys = (value: Record<string, unknown>, required: string[], optional: string[] = []) => {
  const actual = Object.keys(value).sort();
  return actual.length >= required.length && required.every((key) => key in value)
    && actual.every((key) => required.includes(key) || optional.includes(key));
};
const positiveIdOrNull = (value: unknown) => value === null
  || typeof value === "number" && Number.isSafeInteger(value) && value > 0;
function checkedCorrectionReadiness(value: unknown, org: string, receipt: Receipt): CorrectionReadiness {
  const invalid = () => new Error("Проверка исправления вернула неверное юрлицо, редакцию или классификацию.");
  if (!value || typeof value !== "object" || Array.isArray(value) || !receipt.correction_of) throw invalid();
  const data = value as Record<string, unknown>;
  const required = ["organization_id", "receipt_id", "current_version", "correction_of", "classification",
    ...correctionFlagNames, "posting_available", "wms_movement_available", "blockers"];
  const positiveInteger = (item: unknown) => typeof item === "number" && Number.isSafeInteger(item) && item > 0;
  if (!exactKeys(data, required)
    || !positiveInteger(Number(org)) || data.organization_id !== Number(org)
    || data.receipt_id !== receipt.id || data.current_version !== receipt.version
    || !positiveInteger(data.organization_id) || !positiveInteger(data.receipt_id) || !positiveInteger(data.current_version)
    || !data.correction_of || typeof data.correction_of !== "object" || Array.isArray(data.correction_of)
    || !exactKeys(data.correction_of as Record<string, unknown>, ["receipt_id", "version", "entry_id"])
    || !positiveInteger((data.correction_of as Record<string, unknown>).receipt_id)
    || !positiveInteger((data.correction_of as Record<string, unknown>).version)
    || !positiveInteger((data.correction_of as Record<string, unknown>).entry_id)
    || (data.correction_of as Record<string, unknown>).receipt_id !== receipt.correction_of.receipt_id
    || (data.correction_of as Record<string, unknown>).version !== receipt.correction_of.version
    || (data.correction_of as Record<string, unknown>).entry_id !== receipt.correction_of.entry_id
    || correctionFlagNames.some((flag) => typeof data[flag] !== "boolean")
    || data.posting_available !== false || data.wms_movement_available !== false
    || !Array.isArray(data.classification) || !data.classification.every((flag) => typeof flag === "string")
    || !Array.isArray(data.blockers) || !data.blockers.every((blocker) => typeof blocker === "string" && blocker.trim().length > 0)
    || new Set(data.blockers as string[]).size !== (data.blockers as string[]).length) throw invalid();
  const flags = Object.fromEntries(correctionFlagNames.map((flag) => [flag, data[flag]])) as Record<CorrectionFlag, boolean>;
  const classification = correctionFlagNames.filter((flag) => flags[flag]);
  const economicChange = correctionFlagNames.slice(0, 5).some((flag) => flags[flag]);
  const expectedBlockers = [
    ...(flags.physical_change ? ["physical_receipt_adjustment_required"] : []),
    ...(flags.inventory_value_change ? ["inventory_cost_layer_correction_required"] : []),
    ...(flags.vat_change ? ["vat_register_and_eschf_evidence_required"] : []),
    ...(flags.primary_document_change ? ["primary_document_reissue_evidence_required"] : []),
    ...(economicChange ? ["correction_posting_period_required"] : []),
    ...(flags.explanation_only || flags.no_difference ? ["no_economic_difference"] : []),
    "posting_workflow_not_approved",
  ];
  if (data.classification.length !== classification.length
    || data.classification.some((flag, index) => flag !== classification[index])
    || Number(economicChange) + Number(flags.explanation_only) + Number(flags.no_difference) !== 1
    || (flags.explanation_only && (flags.no_difference || correctionFlagNames.slice(0, 5).some((flag) => flags[flag])))
    || (flags.no_difference && correctionFlagNames.slice(0, 6).some((flag) => flags[flag]))
    || data.blockers.length !== expectedBlockers.length
    || data.blockers.some((blocker, index) => blocker !== expectedBlockers[index])) throw invalid();
  return data as CorrectionReadiness;
}
function correctionBlockerLabel(code: string) {
  const labels: Record<string, string> = {
    physical_receipt_adjustment_required: "Нужна отдельная корректировка физической приёмки.",
    inventory_cost_layer_correction_required: "Нужна отдельная корректировка слоя себестоимости.",
    vat_register_and_eschf_evidence_required: "Нужна отдельная сверка НДС и подтверждение по ЭСЧФ.",
    primary_document_reissue_evidence_required: "Нужно подтверждение исправленного первичного документа.",
    correction_posting_period_required: "Нужно отдельно определить период учёта исправления.",
    no_economic_difference: "Экономические реквизиты исправления не отличаются.",
    posting_workflow_not_approved: "Процесс проведения исправлений пока не утверждён.",
  };
  return labels[code] ?? "Сервер сообщил дополнительное ограничение для исправления.";
}
function validSavedDocument(value: unknown): value is Document {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const document = value as Record<string, unknown>;
  const required = ["currency", "invoice_reference", "document_date", "operation_date", "supplier", "supplier_id",
    "supplier_unp", "contract", "warehouse", "explanation", "items"];
  if (!exactKeys(document, required, ["contract_id", "contract_basis", "warehouse_id", "warehouse_title"])
    || !["currency", "invoice_reference", "document_date", "operation_date", "supplier", "contract", "warehouse", "explanation"]
      .every((key) => typeof document[key] === "string")
    || !positiveIdOrNull(document.supplier_id)
    || !(document.supplier_unp === null || typeof document.supplier_unp === "string")
    || !(document.contract_id === undefined || positiveIdOrNull(document.contract_id) && document.contract_id !== null)
    || !(document.contract_basis === undefined || typeof document.contract_basis === "string")
    || !(document.warehouse_id === undefined || positiveIdOrNull(document.warehouse_id))
    || !(document.warehouse_title === undefined || document.warehouse_title === null || typeof document.warehouse_title === "string")
    || ((document.warehouse_id === undefined || document.warehouse_id === null)
      !== (document.warehouse_title === undefined || document.warehouse_title === null))
    || !Array.isArray(document.items) || document.items.length < 1 || document.items.length > 300) return false;
  const lineRequired = ["order_id", "sku_id", "sku_title", "sku", "unit", "lot", "quantity", "net_amount", "vat_rate", "vat_amount", "vat_basis"];
  return document.items.every((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const line = value as Record<string, unknown>;
    return exactKeys(line, lineRequired, ["order_line_id"])
      && positiveIdOrNull(line.order_id) && positiveIdOrNull(line.sku_id)
      && (line.order_line_id === undefined || positiveIdOrNull(line.order_line_id) && line.order_line_id !== null)
      && (line.sku_title === null || typeof line.sku_title === "string")
      && (line.unit === null || typeof line.unit === "string")
      && ["sku", "lot", "quantity", "net_amount", "vat_rate", "vat_amount", "vat_basis"]
        .every((key) => typeof line[key] === "string");
  });
}
function expectedSavedDocument(document: Document) {
  const decimal = (value: unknown, scale: number, positive = false) => {
    if (typeof value !== "string") throw new Error("Суммы и количество должны быть точными строками.");
    const text = value.trim();
    if (!text) return text;
    const match = /^\+?(?:(\d+)(?:\.(\d*))?|\.(\d+))$/.exec(text);
    if (!match) throw new Error("Используйте обычную десятичную запись без знака минус и экспоненты.");
    const fraction = match[2] ?? match[3] ?? "";
    if (fraction.length > scale) throw new Error(`Допустимо не более ${scale} знаков после запятой.`);
    const whole = (match[1] ?? "0").replace(/^0+(?=\d)/, "");
    if (positive && !/[1-9]/.test(whole + fraction)) throw new Error("Количество должно быть больше нуля.");
    return fraction ? `${whole}.${fraction}` : whole;
  };
  const trim = (value: unknown): unknown => {
    if (typeof value === "string") return value.trim();
    if (Array.isArray(value)) return value.map(trim);
    if (value && typeof value === "object") return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, child]) => [key, trim(child)]),
    );
    return value;
  };
  const saved = trim(structuredClone(document)) as Record<string, unknown>;
  if (saved.contract_id === null) delete saved.contract_id;
  if (saved.contract_basis === null) delete saved.contract_basis;
  saved.items = (saved.items as Record<string, unknown>[]).map((line) => {
    const copy: Record<string, unknown> = { ...line,
      quantity: decimal(line.quantity, 6, true),
      net_amount: decimal(line.net_amount, 2),
      vat_rate: decimal(line.vat_rate, 2),
      vat_amount: decimal(line.vat_amount, 2) };
    if (copy.order_line_id === null) delete copy.order_line_id;
    return copy;
  });
  return saved;
}
function readPendingSave(org: string): PendingSave | null {
  const raw = sessionStorage.getItem(saveJournalKey(org));
  if (raw === null) return null;
  let value: unknown;
  try { value = JSON.parse(raw); }
  catch { throw new Error("Журнал сохранения накладной повреждён. Новые отправки заблокированы до проверки реестра."); }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Журнал сохранения накладной повреждён. Новые отправки заблокированы до проверки реестра.");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== ["closeAfterSave", "document", "key", "org", "receiptId", "version"].sort().join(",")
    || row.org !== org || (row.receiptId !== null && (typeof row.receiptId !== "number" || !Number.isSafeInteger(row.receiptId) || row.receiptId < 1))
    || typeof row.version !== "number" || !Number.isSafeInteger(row.version) || row.version < 0 || typeof row.key !== "string" || !row.key
    || (row.receiptId === null ? row.version !== 0 : row.version < 1)
    || typeof row.closeAfterSave !== "boolean" || !validSavedDocument(row.document)
    || canonical(expectedSavedDocument(row.document)) !== canonical(row.document)) {
    throw new Error("Журнал сохранения накладной повреждён. Новые отправки заблокированы до проверки реестра.");
  }
  return value as PendingSave;
}
function storePendingSave(command: PendingSave) {
  const raw = JSON.stringify(command);
  sessionStorage.setItem(saveJournalKey(command.org), raw);
  if (sessionStorage.getItem(saveJournalKey(command.org)) !== raw) throw new Error("Не удалось надёжно сохранить запрос накладной. Отправка не выполнена.");
}
function clearPendingSave(command: PendingSave) {
  const key = saveJournalKey(command.org);
  const raw = sessionStorage.getItem(key);
  try {
    if (raw !== null && canonical(JSON.parse(raw)) === canonical(command)) sessionStorage.removeItem(key);
  } catch { /* Keep unreadable evidence for explicit recovery. */ }
}
const supplierSnapshot = (document: Document) => `${shown(document.supplier)} · УНП ${shown(document.supplier_unp)} · ${document.supplier_id ? `ID ${document.supplier_id}` : "без связи со справочником"}`;
const warehouseSnapshot = (document: Document) => `${shown(document.warehouse)} · ${shown(document.warehouse_title)} · ${document.warehouse_id ? `ID ${document.warehouse_id}` : "без связи со справочником"}`;
function revisionChanges(previous: Document, current: Document) {
  const changes: { label: string; before: string; after: string }[] = [];
  const add = (label: string, before: unknown, after: unknown) => {
    if (JSON.stringify(before) !== JSON.stringify(after)) changes.push({ label, before: shown(before), after: shown(after) });
  };
  add("Валюта", previous.currency, current.currency);
  for (const [field, label] of fields) add(label, previous[field], current[field]);
  add("Поставщик", supplierSnapshot(previous), supplierSnapshot(current));
  add("Склад (справочник)", warehouseSnapshot(previous), warehouseSnapshot(current));
  add("ID договора", previous.contract_id, current.contract_id);
  add("Основание без зарегистрированного договора", previous.contract_basis, current.contract_basis);
  for (let index = 0; index < Math.max(previous.items.length, current.items.length); index++) {
    const before = previous.items[index], after = current.items[index];
    if (!before || !after) add(`Строка ${index + 1}`, before ? "есть" : null, after ? "есть" : null);
    for (const [field, label] of itemHistoryFields) {
      add(`Строка ${index + 1} · ${label}`,
        (before as unknown as Record<string, unknown> | undefined)?.[field],
        (after as unknown as Record<string, unknown> | undefined)?.[field]);
    }
  }
  return changes;
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/procurement${path}`, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(response.status === 409
    ? `Версия или ключ документа уже изменены. Обновите список и откройте актуальную накладную.${typeof data.detail === "string" ? ` Причина: ${data.detail}` : ""}`
    : typeof data.detail === "string" ? data.detail : "Проверьте реквизиты, даты и суммы накладной."), { status: response.status });
  return data;
}
async function accountingRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { cache: "no-store", ...options });
  let data: unknown;
  try {
    data = await response.json();
    if (!data || typeof data !== "object") throw new Error("Malformed response");
  } catch {
    throw new Error("Сервис доказательств НДС вернул некорректный ответ.");
  }
  const detail = !Array.isArray(data) && typeof (data as Record<string, unknown>).detail === "string"
    ? (data as Record<string, unknown>).detail as string : null;
  if (!response.ok) throw Object.assign(new Error(detail ?? "Не удалось сохранить или загрузить проверочные данные НДС."), { status: response.status });
  return data as T;
}
function evidenceScopePath(org: string, receipt: Receipt, kind: InboundVatEvidenceKind) {
  return `/organizations/${org}/receipt-correction-evidence-files?receipt_id=${receipt.id}&receipt_version=${receipt.version}&kind=${kind}`;
}
function checkedEvidenceFile(value: unknown, org: string, receipt: Receipt, kind: InboundVatEvidenceKind): InboundVatEvidenceFile {
  const invalid = () => new Error("Список доказательств вернул повреждённые данные или данные другой накладной.");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const row = value as Record<string, unknown>;
  const required = ["file_id", "organization_id", "receipt_id", "receipt_version", "kind", "tax_period", "reference", "filename", "content_type", "size_bytes", "sha256", "evidence", "request_key", "supersedes_id", "digest", "actor", "created_at", "is_current", "bytes_verified_at_upload", "signature_verified", "document_facts_verified", "posting_available"];
  const numeric = (n: unknown) => typeof n === "number" && Number.isSafeInteger(n) && n > 0;
  const type = evidenceKinds.find((item) => item.kind === kind)!;
  if (!exactKeys(row, required)
    || row.organization_id !== Number(org) || row.receipt_id !== receipt.id || row.receipt_version !== receipt.version || row.kind !== kind
    || !numeric(row.file_id) || !numeric(row.organization_id) || !numeric(row.receipt_id) || !numeric(row.receipt_version)
    || typeof row.tax_period !== "string" || !/^\d{4}-(0[1-9]|1[0-2])$/.test(row.tax_period)
    || typeof row.reference !== "string" || !row.reference.trim() || row.reference.length > 160
    || typeof row.filename !== "string" || row.filename.length < 1 || row.filename.length > 160 || /[/\\\r\n\0]/.test(row.filename) || !row.filename.toLowerCase().endsWith(type.extension)
    || typeof row.content_type !== "string" || !type.mime.includes(row.content_type)
    || typeof row.size_bytes !== "number" || !numeric(row.size_bytes) || row.size_bytes > evidenceMaxBytes
    || typeof row.sha256 !== "string" || !evidenceSha256.test(row.sha256)
    || typeof row.evidence !== "string" || row.evidence.trim().length < 10 || row.evidence.length > 2000
    || typeof row.request_key !== "string" || !secureUuid.test(row.request_key)
    || !(row.supersedes_id === null || numeric(row.supersedes_id))
    || typeof row.digest !== "string" || !evidenceSha256.test(row.digest)
    || typeof row.actor !== "string" || !row.actor.trim()
    || typeof row.created_at !== "string" || !Number.isFinite(Date.parse(row.created_at))
    || typeof row.is_current !== "boolean" || row.bytes_verified_at_upload !== true
    || row.signature_verified !== false || row.document_facts_verified !== false || row.posting_available !== false) throw invalid();
  return row as InboundVatEvidenceFile;
}
function checkedEvidenceList(value: unknown, org: string, receipt: Receipt, kind: InboundVatEvidenceKind): InboundVatEvidenceFile[] {
  if (!Array.isArray(value)) throw new Error("Список доказательств НДС имеет неверный формат.");
  const rows = value.map((row) => checkedEvidenceFile(row, org, receipt, kind));
  const ids = new Set<number>();
  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    if (ids.has(row.file_id) || row.is_current !== (index === rows.length - 1)
      || (index === 0 ? row.supersedes_id !== null : row.supersedes_id !== rows[index - 1].file_id))
      throw new Error("История доказательств НДС нарушена; отображение и замена файлов заблокированы.");
    ids.add(row.file_id);
  }
  return rows;
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}
function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}
function validIsoDate(value: unknown) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value));
}
function workpaperFlagsMatch(value: Record<string, unknown>) {
  return Object.entries(inboundVatWorkpaperFlags).every(([key, expected]) => value[key] === expected);
}
function checkedCurrentWorkpaperEvidence(value: InboundVatEvidenceState, org: string, receipt: Receipt,
  taxPeriod: string): InboundVatWorkpaperEvidence[] {
  if (!receipt.correction_of || !taxPeriodPattern.test(taxPeriod))
    throw new Error("Укажите допустимый налоговый период для текущей редакции исправления.");
  if (value.context !== JSON.stringify([org, org, receipt.id, receipt.version, receipt.correction_of.receipt_id,
    receipt.correction_of.version, receipt.correction_of.entry_id]) || value.status !== "ready" || !value.files)
    throw new Error("Не загружены проверенные доказательства текущей редакции исправления.");
  const files = Object.values(value.files).flatMap((history) => history.at(-1) ? [history.at(-1)!] : []);
  if (!files.length) throw new Error("Для просмотра рабочей ведомости требуется хотя бы один текущий файл доказательства.");
  if (files.some((file) => file.organization_id !== Number(org) || file.receipt_id !== receipt.id
    || file.receipt_version !== receipt.version || file.is_current !== true || file.bytes_verified_at_upload !== true
    || !evidenceSha256.test(file.sha256) || !evidenceSha256.test(file.digest)))
    throw new Error("Доказательство не привязано к текущему юрлицу и редакции либо его байты не проверены.");
  if (files.some((file) => file.tax_period !== taxPeriod))
    throw new Error("Налоговый период должен совпадать с периодом каждого текущего файла доказательства.");
  return files.map(({ file_id, receipt_id, receipt_version, kind, tax_period, reference, filename,
    content_type, size_bytes, sha256, digest }) => ({ file_id, receipt_id, receipt_version, kind,
    tax_period, reference, filename, content_type, size_bytes, sha256, digest }))
    .sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.file_id - b.file_id));
}
function checkedWorkpaperSnapshot(value: unknown, org: string, receipt: Receipt, taxPeriod: string): InboundVatWorkpaperSnapshot {
  const invalid = () => new Error("Снимок рабочей ведомости не совпадает с юрлицом, исправлением или безопасным review-only контрактом.");
  if (!isRecord(value)) throw invalid();
  const snapshot = value;
  const snapshotKeys = ["organization_id", "receipt", "tax_period", "classification", "source_account_18_lines", "evidence_files",
    ...Object.keys(inboundVatWorkpaperFlags)];
  const sourceKeys = ["correction_receipt_id", "correction_version", "correction_revision_id", "correction_document_digest",
    "original_receipt_id", "original_version", "original_revision_id", "original_document_digest", "source_entry_id",
    "source_entry", "source_version", "source_entry_digest", "source_posting_date", "source_operation_date"];
  const lineKeys = ["line_id", "account_id", "account_code", "account_title", "category", "cash", "amount", "currency", "dimensions"];
  const evidenceKeys = ["file_id", "receipt_id", "receipt_version", "kind", "tax_period", "reference", "filename",
    "content_type", "size_bytes", "sha256", "digest"];
  if (!exactKeys(snapshot, snapshotKeys) || !workpaperFlagsMatch(snapshot)
    || snapshot.organization_id !== Number(org) || !positiveInteger(snapshot.organization_id)
    || snapshot.tax_period !== taxPeriod || !taxPeriodPattern.test(taxPeriod)
    || !Array.isArray(snapshot.classification) || snapshot.classification.length !== 1 || snapshot.classification[0] !== "vat_change"
    || !isRecord(snapshot.receipt) || !exactKeys(snapshot.receipt, sourceKeys)) throw invalid();
  const source = snapshot.receipt;
  if (!positiveInteger(source.correction_receipt_id) || source.correction_receipt_id !== receipt.id
    || !positiveInteger(source.correction_version) || source.correction_version !== receipt.version
    || !positiveInteger(source.correction_revision_id)
    || typeof source.correction_document_digest !== "string" || !evidenceSha256.test(source.correction_document_digest)
    || !positiveInteger(source.original_receipt_id) || source.original_receipt_id !== receipt.correction_of?.receipt_id
    || !positiveInteger(source.original_version) || source.original_version !== receipt.correction_of?.version
    || !positiveInteger(source.original_revision_id)
    || typeof source.original_document_digest !== "string" || !evidenceSha256.test(source.original_document_digest)
    || !positiveInteger(source.source_entry_id) || source.source_entry_id !== receipt.correction_of?.entry_id
    || source.source_entry !== `procurement:receipt:${source.original_receipt_id}`
    || source.source_version !== source.original_version
    || typeof source.source_entry_digest !== "string" || !evidenceSha256.test(source.source_entry_digest)
    || !validIsoDate(source.source_posting_date) || !validIsoDate(source.source_operation_date)
    || !Array.isArray(snapshot.source_account_18_lines) || snapshot.source_account_18_lines.length < 1
    || !Array.isArray(snapshot.evidence_files) || snapshot.evidence_files.length < 1) throw invalid();
  const lineIds = new Set<number>();
  for (const candidate of snapshot.source_account_18_lines) {
    if (!isRecord(candidate) || !exactKeys(candidate, lineKeys)
      || !positiveInteger(candidate.line_id) || lineIds.has(candidate.line_id)
      || !positiveInteger(candidate.account_id) || typeof candidate.account_code !== "string"
      || !(candidate.account_code === "18" || candidate.account_code.startsWith("18."))
      || typeof candidate.account_title !== "string" || typeof candidate.category !== "string"
      || typeof candidate.cash !== "boolean" || typeof candidate.amount !== "string"
      || !/^\d+\.\d{2}$/.test(candidate.amount) || typeof candidate.currency !== "string"
      || !isRecord(candidate.dimensions)) throw invalid();
    lineIds.add(candidate.line_id);
  }
  const evidenceIds = new Set<number>();
  for (const candidate of snapshot.evidence_files) {
    if (!isRecord(candidate) || !exactKeys(candidate, evidenceKeys)
      || !positiveInteger(candidate.file_id) || evidenceIds.has(candidate.file_id)
      || candidate.receipt_id !== receipt.id || candidate.receipt_version !== receipt.version
      || (candidate.kind !== "supplier_eschf_xml" && candidate.kind !== "supporting_document_pdf")
      || candidate.tax_period !== taxPeriod || typeof candidate.reference !== "string" || !candidate.reference.trim()
      || typeof candidate.filename !== "string" || !candidate.filename.trim()
      || typeof candidate.content_type !== "string" || !candidate.content_type.trim()
      || !positiveInteger(candidate.size_bytes) || typeof candidate.sha256 !== "string" || !evidenceSha256.test(candidate.sha256)
      || typeof candidate.digest !== "string" || !evidenceSha256.test(candidate.digest)) throw invalid();
    evidenceIds.add(candidate.file_id);
  }
  return snapshot as unknown as InboundVatWorkpaperSnapshot;
}
async function sha256Canonical(value: unknown) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value)));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
async function checkedWorkpaperPreview(value: unknown, org: string, receipt: Receipt, taxPeriod: string,
  expectedEvidence: InboundVatWorkpaperEvidence[]): Promise<InboundVatWorkpaperPreview> {
  const invalid = () => new Error("Предпросмотр рабочей ведомости вернул повреждённую или устаревшую область данных.");
  if (!isRecord(value)) throw invalid();
  const row = value;
  const keys = ["organization_id", "receipt_id", "receipt_version", "original_receipt_id", "original_version", "tax_period",
    "basis", "basis_digest", "status", "source_account_18_line_count", "current_evidence_file_count", "evidence_bytes_verified_at_review",
    ...Object.keys(inboundVatWorkpaperFlags)];
  if (!exactKeys(row, keys) || !workpaperFlagsMatch(row)
    || row.organization_id !== Number(org) || row.receipt_id !== receipt.id || row.receipt_version !== receipt.version
    || row.original_receipt_id !== receipt.correction_of?.receipt_id || row.original_version !== receipt.correction_of?.version
    || row.tax_period !== taxPeriod || row.status !== "review_only_workpaper_ready" || row.evidence_bytes_verified_at_review !== true
    || !positiveInteger(row.source_account_18_line_count) || !positiveInteger(row.current_evidence_file_count)
    || typeof row.basis_digest !== "string" || !evidenceSha256.test(row.basis_digest)) throw invalid();
  const basis = checkedWorkpaperSnapshot(row.basis, org, receipt, taxPeriod);
  if (basis.source_account_18_lines.length !== row.source_account_18_line_count
    || basis.evidence_files.length !== row.current_evidence_file_count
    || canonical(basis.evidence_files) !== canonical(expectedEvidence)
    || await sha256Canonical(basis) !== row.basis_digest) throw invalid();
  return row as unknown as InboundVatWorkpaperPreview;
}
async function checkedWorkpaperResult(value: unknown, org: string, receipt: Receipt, taxPeriod: string,
  expectedBody?: InboundVatWorkpaperConfirmBody): Promise<InboundVatWorkpaperResult> {
  const invalid = () => new Error("Сохранённая рабочая ведомость не подтверждает точный запрос, источник или review-only ограничения.");
  if (!isRecord(value)) throw invalid();
  const row = value;
  const keys = ["workpaper_id", "organization_id", "receipt_id", "receipt_version", "original_receipt_id", "original_version",
    "source_entry_id", "source_entry_digest", "tax_period", "revision", "supersedes_workpaper_id", "request_key", "request_digest",
    "basis_digest", "snapshot_digest", "reviewer_evidence", "reviewed_by", "created_at", "snapshot", "status",
    "evidence_bytes_verified_at_review", ...Object.keys(inboundVatWorkpaperFlags)];
  if (!exactKeys(row, keys) || !workpaperFlagsMatch(row)
    || !positiveInteger(row.workpaper_id) || row.organization_id !== Number(org)
    || row.receipt_id !== receipt.id || row.receipt_version !== receipt.version
    || row.original_receipt_id !== receipt.correction_of?.receipt_id || row.original_version !== receipt.correction_of?.version
    || row.tax_period !== taxPeriod || !positiveInteger(row.revision)
    || !(row.supersedes_workpaper_id === null || positiveInteger(row.supersedes_workpaper_id))
    || typeof row.request_key !== "string" || !secureUuid.test(row.request_key)
    || typeof row.request_digest !== "string" || !evidenceSha256.test(row.request_digest)
    || typeof row.basis_digest !== "string" || !evidenceSha256.test(row.basis_digest)
    || typeof row.snapshot_digest !== "string" || !evidenceSha256.test(row.snapshot_digest)
    || typeof row.reviewer_evidence !== "string" || row.reviewer_evidence.trim().length < 10
    || typeof row.reviewed_by !== "string" || !row.reviewed_by.trim()
    || typeof row.created_at !== "string" || !Number.isFinite(Date.parse(row.created_at))
    || row.status !== "review_only_workpaper" || row.evidence_bytes_verified_at_review !== true) throw invalid();
  const snapshot = checkedWorkpaperSnapshot(row.snapshot, org, receipt, taxPeriod);
  const body: InboundVatWorkpaperConfirmBody = expectedBody ?? {
    request_key: row.request_key as string,
    receipt_id: receipt.id,
    receipt_version: receipt.version,
    tax_period: taxPeriod,
    basis_digest: row.basis_digest as string,
    reviewer_evidence: (row.reviewer_evidence as string).trim(),
    supersedes_workpaper_id: row.supersedes_workpaper_id as number | null,
  };
  if (row.request_key !== body.request_key || body.receipt_id !== receipt.id || body.receipt_version !== receipt.version
    || body.tax_period !== taxPeriod || row.basis_digest !== body.basis_digest
    || row.reviewer_evidence !== body.reviewer_evidence.trim() || row.supersedes_workpaper_id !== body.supersedes_workpaper_id
    || row.source_entry_id !== snapshot.receipt.source_entry_id || row.source_entry_digest !== snapshot.receipt.source_entry_digest
    || await sha256Canonical(snapshot) !== row.snapshot_digest || row.snapshot_digest !== row.basis_digest
    || await sha256Canonical({ ...body, reviewer_evidence: body.reviewer_evidence.trim() }) !== row.request_digest) throw invalid();
  return row as unknown as InboundVatWorkpaperResult;
}
function workpaperHistoryChain(value: unknown, org: string, receipt: Receipt, taxPeriod: string): Promise<InboundVatWorkpaperResult[]> {
  if (!Array.isArray(value)) throw new Error("История рабочих ведомостей вернула неверный формат.");
  return Promise.all(value.map((row) => checkedWorkpaperResult(row, org, receipt, taxPeriod))).then((items) => {
    const ids = new Set<number>();
    for (let index = 0; index < items.length; index++) {
      const item = items[index];
      const previous = items[index - 1];
      if (ids.has(item.workpaper_id) || item.revision !== index + 1
        || (index === 0 ? item.supersedes_workpaper_id !== null
          : item.supersedes_workpaper_id !== previous!.workpaper_id))
        throw new Error("История рабочих ведомостей нарушает последовательность неизменяемых редакций.");
      ids.add(item.workpaper_id);
    }
    return items;
  });
}
const workpaperJournalKey = (org: string, receiptId: number, receiptVersion: number, taxPeriod: string) =>
  `inbound-vat-correction-workpaper:v1:${org}:${receiptId}:${receiptVersion}:${taxPeriod}`;
function readPendingWorkpaper(org: string, receipt: Receipt, taxPeriod: string): PendingInboundVatWorkpaper | null {
  const raw = sessionStorage.getItem(workpaperJournalKey(org, receipt.id, receipt.version, taxPeriod));
  if (raw === null) return null;
  const invalid = () => new Error("Журнал подтверждения рабочей ведомости повреждён; новый запрос для этой области заблокирован.");
  let value: unknown;
  try { value = JSON.parse(raw); } catch { throw invalid(); }
  if (!isRecord(value) || !exactKeys(value, ["organization_id", "receipt_id", "receipt_version", "tax_period", "request_key", "body_json"])) throw invalid();
  let bodyValue: unknown;
  try { bodyValue = JSON.parse(String(value.body_json)); } catch { throw invalid(); }
  const bodyKeys = ["request_key", "receipt_id", "receipt_version", "tax_period", "basis_digest", "reviewer_evidence", "supersedes_workpaper_id"];
  if (!isRecord(bodyValue) || !exactKeys(bodyValue, bodyKeys)
    || value.organization_id !== Number(org) || value.receipt_id !== receipt.id || value.receipt_version !== receipt.version
    || value.tax_period !== taxPeriod || typeof value.request_key !== "string" || !secureUuid.test(value.request_key)
    || typeof value.body_json !== "string" || !positiveInteger(bodyValue.receipt_id) || bodyValue.receipt_id !== receipt.id
    || !positiveInteger(bodyValue.receipt_version) || bodyValue.receipt_version !== receipt.version
    || bodyValue.tax_period !== taxPeriod || bodyValue.request_key !== value.request_key
    || typeof bodyValue.basis_digest !== "string" || !evidenceSha256.test(bodyValue.basis_digest)
    || typeof bodyValue.reviewer_evidence !== "string" || bodyValue.reviewer_evidence.trim().length < 10
    || bodyValue.reviewer_evidence.trim() !== bodyValue.reviewer_evidence
    || !(bodyValue.supersedes_workpaper_id === null || positiveInteger(bodyValue.supersedes_workpaper_id))) throw invalid();
  return { organization_id: value.organization_id as number, receipt_id: value.receipt_id as number,
    receipt_version: value.receipt_version as number, tax_period: taxPeriod, request_key: value.request_key as string,
    body: bodyValue as unknown as InboundVatWorkpaperConfirmBody, body_json: value.body_json as string, journal_json: raw };
}
function storePendingWorkpaper(command: Omit<PendingInboundVatWorkpaper, "journal_json">) {
  const journal = { organization_id: command.organization_id, receipt_id: command.receipt_id,
    receipt_version: command.receipt_version, tax_period: command.tax_period, request_key: command.request_key,
    body_json: command.body_json };
  const raw = JSON.stringify(journal);
  const key = workpaperJournalKey(String(command.organization_id), command.receipt_id, command.receipt_version, command.tax_period);
  sessionStorage.setItem(key, raw);
  if (sessionStorage.getItem(key) !== raw) throw new Error("Не удалось сохранить точный запрос рабочей ведомости. Отправка не выполнена.");
  return { ...command, journal_json: raw };
}
function clearPendingWorkpaper(command: PendingInboundVatWorkpaper, org: string, receipt: Receipt) {
  const key = workpaperJournalKey(org, receipt.id, receipt.version, command.tax_period);
  if (sessionStorage.getItem(key) === command.journal_json) sessionStorage.removeItem(key);
}
function pendingWorkpaperJournalsForReceipt(org: string, receiptId: number) {
  const prefix = `inbound-vat-correction-workpaper:v1:${org}:${receiptId}:`;
  const journals: { key: string; receipt_version: number | null; tax_period: string | null }[] = [];
  for (let index = 0; index < sessionStorage.length; index++) {
    const key = sessionStorage.key(index);
    if (!key?.startsWith(prefix)) continue;
    const [versionText, taxPeriod, ...extra] = key.slice(prefix.length).split(":");
    const version = /^\d+$/.test(versionText) ? Number(versionText) : null;
    journals.push({ key, receipt_version: positiveInteger(version) ? version : null,
      tax_period: extra.length === 0 && taxPeriodPattern.test(taxPeriod) ? taxPeriod : null });
  }
  return journals.sort((a, b) => (a.receipt_version ?? 0) - (b.receipt_version ?? 0)
    || (a.tax_period ?? "").localeCompare(b.tax_period ?? "") || a.key.localeCompare(b.key));
}
function pendingWorkpaperJournalForReceipt(org: string, receiptId: number) {
  return pendingWorkpaperJournalsForReceipt(org, receiptId)[0] ?? null;
}
function receiptAtWorkpaperVersion(receipt: Receipt, version: number): Receipt {
  const revisions = receipt.revisions.filter((revision) => revision.version <= version);
  if (!receipt.correction_of || !positiveInteger(version) || !revisions.some((revision) => revision.version === version))
    throw new Error(`Редакция исправления ${version} отсутствует в загруженной истории.`);
  return { ...receipt, version, revisions };
}
function WorkpaperSnapshotDetails({ snapshot }: { snapshot: InboundVatWorkpaperSnapshot }) {
  const source = snapshot.receipt;
  return <div className="space-y-2 text-sm">
    <p>Исправление: накладная № {source.correction_receipt_id}, версия {source.correction_version}, снимок редакции № {source.correction_revision_id} · SHA-256 документа {source.correction_document_digest}</p>
    <p>Исходная накладная: № {source.original_receipt_id}, версия {source.original_version}, снимок редакции № {source.original_revision_id} · SHA-256 документа {source.original_document_digest}</p>
    <p>Исходная проводка: запись № {source.source_entry_id} ({source.source_entry}), версия {source.source_version} · SHA-256 {source.source_entry_digest}</p>
    <p>Даты источника: проводка {source.source_posting_date}, операция {source.source_operation_date} · классификация: только изменение НДС.</p>
    <div><h5 className="font-medium">Строки исходной проводки по счёту 18</h5>
      <ul className="list-disc pl-5">{snapshot.source_account_18_lines.map((line) =>
        <li key={line.line_id}>Строка № {line.line_id} · счёт {line.account_code} · {line.account_title} · {line.amount} {line.currency}</li>)}</ul>
    </div>
    <div><h5 className="font-medium">Файлы, привязанные к рабочей ведомости · период {snapshot.tax_period}</h5>
      <ul className="list-disc pl-5">{snapshot.evidence_files.map((file) => <li key={file.file_id}>
        Файл № {file.file_id} · {file.kind} · {file.filename} · SHA-256 {file.sha256} · digest {file.digest}
      </li>)}</ul>
    </div>
    <dl className="grid gap-1 md:grid-cols-2">
      <div><dt>Review-only</dt><dd>{snapshot.review_only ? "Да" : "Нет"}</dd></div>
      <div><dt>Подпись проверена</dt><dd>{snapshot.signature_verified ? "Да" : "Нет"}</dd></div>
      <div><dt>Факты документа проверены</dt><dd>{snapshot.document_facts_verified ? "Да" : "Нет"}</dd></div>
      <div><dt>Право на вычет оценено</dt><dd>{snapshot.deduction_eligibility_assessed ? "Да" : "Нет"}</dd></div>
      <div><dt>Принято бухгалтером</dt><dd>{snapshot.accountant_accepted ? "Да" : "Нет"}</dd></div>
      <div><dt>Проведение доступно</dt><dd>{snapshot.posting_available ? "Да" : "Нет"}</dd></div>
    </dl>
  </div>;
}
function vatOnlyEvidenceAllowed(readiness: CorrectionReadiness | undefined, org: string, receipt: Receipt) {
  return Boolean(readiness && receipt.correction_of && Number(org) > 0
    && readiness.organization_id === Number(org) && readiness.receipt_id === receipt.id
    && readiness.current_version === receipt.version && readiness.posting_available === false
    && readiness.wms_movement_available === false && readiness.vat_change === true
    && readiness.physical_change === false && readiness.inventory_value_change === false
    && readiness.primary_document_change === false && readiness.operation_date_change === false
    && readiness.classification.length === 1 && readiness.classification[0] === "vat_change");
}
function readFileDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать выбранный файл."));
    reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("Не удалось прочитать байты выбранного файла."));
    reader.readAsDataURL(file);
  });
}
async function sha256File(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
function checkedEvidenceUploadFile(file: File, kind: InboundVatEvidenceKind) {
  const type = evidenceKinds.find((item) => item.kind === kind)!;
  if (!file.size || file.size > evidenceMaxBytes) throw new Error("Файл должен быть больше 0 байт и не превышать 10 МиБ.");
  if (!file.name.toLowerCase().endsWith(type.extension) || !type.mime.includes(file.type))
    throw new Error(`Для этого вида доказательства выберите файл ${type.extension} с соответствующим MIME-типом.`);
}
function checkedHistoryPage(data: ContractHistoryPage, org: string, supplierId: number) {
  if (data.organization_id !== Number(org) || data.supplier_id !== supplierId || data.status !== "revoked"
    || !Array.isArray(data.items) || data.items.some((row) => row.organization_id !== Number(org)
      || row.supplier_id !== supplierId || row.is_active !== false)
    || (data.truncated && (typeof data.next_before_at !== "string" || !Number.isInteger(data.next_before_id))))
    throw new Error("История договоров вернула неверные данные юрлица, поставщика или страницы.");
  const next: ContractHistoryCursor | null = data.truncated
    ? { at: data.next_before_at!, id: data.next_before_id! } : null;
  return { items: data.items, next };
}
export function ProcurementReceiptDrafts({ org, initialReceipt, accounts = [], policyId, date = "", onPosted, onPendingChange }: { org: string; initialReceipt?: string; accounts?: ReceiptAccount[]; policyId?: number; date?: string; onPosted?: () => void; onPendingChange?: (pending: boolean) => void }) {
  const [rows, setRows] = useState<Receipt[]>([]), [document, setDocument] = useState(blank);
  const [query, setQuery] = useState(""), [statusFilter, setStatusFilter] = useState("all");
  const [orders, setOrders] = useState<OwnedOrder[]>([]);
  const [orderError, setOrderError] = useState("");
  const [supplierSearch, setSupplierSearch] = useState("");
  const [supplierOptions, setSupplierOptions] = useState<ProcurementSupplierOption[]>([]);
  const [supplierError, setSupplierError] = useState("");
  const [warehouseSearch, setWarehouseSearch] = useState("");
  const [warehouseOptions, setWarehouseOptions] = useState<ReceiptWarehouseOption[]>([]);
  const [warehouseError, setWarehouseError] = useState("");
  const [contracts, setContracts] = useState<SupplierContract[]>([]), [contractError, setContractError] = useState("");
  const [revokedState, setRevokedState] = useState<{ context: string; items: SupplierContract[]; next: ContractHistoryCursor | null; loading: boolean; error: string }>({ context: "", items: [], next: null, loading: false, error: "" });
  const [newContract, setNewContract] = useState({ number: "", title: "", signed_on: "", expires_on: "", evidence: "" });
  const [contractBusy, setContractBusy] = useState(false);
  const [contractRevokeReason, setContractRevokeReason] = useState("");
  const [contractRevokeUncertain, setContractRevokeUncertain] = useState(false);
  const [skuSearch, setSkuSearch] = useState("");
  const [skuOptions, setSkuOptions] = useState<ProcurementSkuOption[]>([]);
  const [skuError, setSkuError] = useState("");
  const [selected, setSelected] = useState<Receipt | null>(null), [selectedOrg, setSelectedOrg] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const [correctionReadiness, setCorrectionReadiness] = useState<CorrectionReadinessState>({ context: "", status: "idle" });
  const [inboundVatEvidence, setInboundVatEvidence] = useState<InboundVatEvidenceState>({ context: "", status: "idle" });
  const [evidenceForms, setEvidenceForms] = useState<Record<InboundVatEvidenceKind, InboundVatEvidenceForm>>({
    supplier_eschf_xml: { file: null, reference: "", tax_period: "", evidence: "" },
    supporting_document_pdf: { file: null, reference: "", tax_period: "", evidence: "" },
  });
  const [evidenceBusy, setEvidenceBusy] = useState<InboundVatEvidenceKind | null>(null);
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const evidenceMessageContext = useRef("");
  const evidenceUploadEpoch = useRef(0);
  const [workpaperTaxPeriod, setWorkpaperTaxPeriod] = useState("");
  const [workpaperReviewerEvidence, setWorkpaperReviewerEvidence] = useState("");
  const [workpaperPreview, setWorkpaperPreview] = useState<InboundVatWorkpaperPreviewState>({ scope: "", evidence_digest: "", status: "idle", error: "" });
  const [workpaperHistory, setWorkpaperHistory] = useState<InboundVatWorkpaperHistoryState>({ scope: "", status: "idle", items: [], error: "" });
  const [pendingWorkpaper, setPendingWorkpaper] = useState<PendingInboundVatWorkpaper | null>(null);
  const [workpaperJournalError, setWorkpaperJournalError] = useState("");
  const [workpaperMessage, setWorkpaperMessage] = useState("");
  const [workpaperBusy, setWorkpaperBusy] = useState<"preview" | "confirm" | "recover" | null>(null);
  const [workpaperHistoryReload, setWorkpaperHistoryReload] = useState(0);
  const workpaperEpoch = useRef(0);
  const workpaperCardEpoch = useRef(0);
  const workpaperHistoryRequest = useRef(0);
  const workpaperJournalLookup = useRef(0);
  const [uncertain, setUncertain] = useState(false);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const [editorOpen, setEditorOpen] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [reload, setReload] = useState(0);
  const [loadedKey, setLoadedKey] = useState("");
  const pending = useRef<PendingSave | null>(null), unknownSave = useRef(false), corruptJournal = useRef(false), active = useRef(true);
  const pendingContractRevoke = useRef<PendingContractRevoke | null>(null);
  const contractFetchVersion = useRef(0), warehouseFetchVersion = useRef(0), supplierContext = useRef("");
  supplierContext.current = `${org}:${document.supplier_id ?? ""}`;
  const revokedContracts = revokedState.context === supplierContext.current ? revokedState.items : [];
  const revokedError = revokedState.context === supplierContext.current ? revokedState.error : "";
  const revokedNext = revokedState.context === supplierContext.current ? revokedState.next : null;
  const revokedLoading = revokedState.context === supplierContext.current && revokedState.loading;
  const initialOpened = useRef(false);
  const [initialLoading, setInitialLoading] = useState(initialReceipt !== undefined);
  const path = `/organizations/${org}/receipt-documents`;
  const listKey = `${path}/${reload}`;
  const listLoaded = loadedKey === listKey;
  const correctionContext = selected?.correction_of
    ? JSON.stringify([org, selectedOrg, selected.id, selected.version, selected.correction_of.receipt_id,
      selected.correction_of.version, selected.correction_of.entry_id]) : "";
  const correctionContextRef = useRef(correctionContext);
  correctionContextRef.current = correctionContext;
  const workpaperScope = selected?.correction_of ? JSON.stringify([correctionContext, workpaperTaxPeriod]) : "";
  const workpaperScopeRef = useRef(workpaperScope);
  workpaperScopeRef.current = workpaperScope;
  const workpaperEvidenceDigest = inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "ready" && inboundVatEvidence.files
    ? canonical(Object.values(inboundVatEvidence.files).flatMap((history) => history.at(-1) ? [history.at(-1)] : []).map((file) => ({
      file_id: file!.file_id, receipt_id: file!.receipt_id, receipt_version: file!.receipt_version, kind: file!.kind,
      tax_period: file!.tax_period, sha256: file!.sha256, digest: file!.digest,
    })).sort((a, b) => (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.file_id - b.file_id))) : "";
  const workpaperEvidenceDigestRef = useRef(workpaperEvidenceDigest);
  workpaperEvidenceDigestRef.current = workpaperEvidenceDigest;
  const correctionReadinessForSelection: CorrectionReadinessState = correctionReadiness.context === correctionContext
    ? correctionReadiness
    : { context: correctionContext, status: selected?.correction_of ? selectedOrg === org ? "loading" : "error" : "idle" };
  const correctionReadinessRef = useRef(correctionReadinessForSelection);
  correctionReadinessRef.current = correctionReadinessForSelection;
  const inboundVatEvidenceRef = useRef(inboundVatEvidence);
  inboundVatEvidenceRef.current = inboundVatEvidence;
  const dirty = JSON.stringify(document) !== JSON.stringify(selected ? selected.revisions.at(-1)!.document : blank());
  const confirmDiscard = useUnsavedDocumentGuard(dirty || busy || uncertain || contractBusy || contractRevokeUncertain, onPendingChange);
  const search = query.trim().toLocaleLowerCase("ru");
  const visible = rows.filter((row) => {
    const source = row.revisions.at(-1)!.document;
    const status = row.posting ? "posted" : "draft";
    return (statusFilter === "all" || statusFilter === status)
      && (!search || [source.invoice_reference, source.supplier, source.document_date]
        .some((value) => value.toLocaleLowerCase("ru").includes(search)));
  });
  const exactWarehouse = warehouseOptions.find((option) => option.id === document.warehouse_id
    && option.name === document.warehouse && option.title === document.warehouse_title);
  const warehouseSelectionValue = exactWarehouse ? String(exactWarehouse.id)
    : document.warehouse_id ? `saved:${document.warehouse_id}` : "";
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    try {
      const saved = readPendingSave(org);
      if (!saved) return;
      pending.current = saved;
      unknownSave.current = true;
      setDocument(structuredClone(saved.document));
      setEditorOpen(true);
      setUncertain(true);
      setRecoveryBlocked(saved.receiptId !== null);
      setInitialLoading(false);
      setNotice("Восстановлена неподтверждённая попытка сохранения. Повтор использует тот же ключ и те же реквизиты.");
    } catch (cause) {
      corruptJournal.current = true;
      setUncertain(true);
      setRecoveryBlocked(true);
      setInitialLoading(false);
      setError(cause instanceof Error ? cause.message : "Не удалось прочитать журнал сохранения накладной.");
    }
  }, [org]);
  useEffect(() => {
    if (!supplierSearch.trim()) return;
    let current = true;
    const timer = window.setTimeout(() => {
      void fetchProcurementSuppliers(Number(org), supplierSearch.trim())
        .then((result) => { if (current) { setSupplierOptions(result.items); setSupplierError(""); } })
        .catch((cause: Error) => { if (current) { setSupplierOptions([]); setSupplierError(cause.message); } });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [org, supplierSearch]);
  useEffect(() => {
    if (!skuSearch.trim()) return;
    let current = true;
    const timer = window.setTimeout(() => {
      void fetchProcurementSkus(Number(org), skuSearch.trim())
        .then((result) => { if (current) { setSkuOptions(result.items); setSkuError(""); } })
        .catch((cause: Error) => { if (current) { setSkuOptions([]); setSkuError(cause.message); } });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [org, skuSearch]);
  useEffect(() => {
    let current = true;
    const generation = ++warehouseFetchVersion.current;
    const timer = window.setTimeout(() => {
      void request<{ organization_id: number; items: unknown[]; truncated: boolean }>(
        `/organizations/${org}/receipt-warehouse-options?q=${encodeURIComponent(warehouseSearch.trim())}`,
      ).then((data) => {
        if (!current || generation !== warehouseFetchVersion.current) return;
        if (data.organization_id !== Number(org) || !Array.isArray(data.items))
          throw new Error("Справочник складов вернул данные другого юрлица.");
        const items = data.items.map((value) => {
          if (!isRecord(value) || !positiveInteger(value.id) || typeof value.name !== "string"
            || !value.name.trim() || typeof value.title !== "string" || !value.title.trim()
            || value.is_active !== true) throw new Error("Справочник складов вернул неверную или неактивную запись.");
          return { id: value.id, name: value.name, title: value.title, is_active: true as const };
        });
        setWarehouseOptions(items); setWarehouseError("");
      }).catch((cause: Error) => {
        if (current && generation === warehouseFetchVersion.current) {
          setWarehouseOptions([]); setWarehouseError(cause.message);
        }
      });
    }, 250);
    return () => { current = false; window.clearTimeout(timer); };
  }, [org, warehouseSearch]);
  useEffect(() => {
    const supplierId = document.supplier_id;
    const generation = ++contractFetchVersion.current;
    if (!supplierId) return;
    let current = true;
    void request<{ organization_id: number; supplier_id: number; items: SupplierContract[] }>(
      `/organizations/${org}/supplier-contracts?supplier_id=${supplierId}`,
    ).then((data) => {
      if (!current || generation !== contractFetchVersion.current) return;
      if (data.organization_id !== Number(org) || data.supplier_id !== supplierId || !Array.isArray(data.items))
        throw new Error("Справочник договоров вернул данные другого юрлица или поставщика.");
      setContracts(data.items); setContractError("");
    }).catch((cause: Error) => { if (current && generation === contractFetchVersion.current) { setContracts([]); setContractError(cause.message); } });
    void request<ContractHistoryPage>(
      `/organizations/${org}/supplier-contracts?supplier_id=${supplierId}&status=revoked`,
    ).then((data) => {
      if (!current || generation !== contractFetchVersion.current) return;
      const page = checkedHistoryPage(data, org, supplierId);
      setRevokedState({ context: `${org}:${supplierId}`, ...page, loading: false, error: "" });
    }).catch((cause: Error) => { if (current && generation === contractFetchVersion.current)
      setRevokedState({ context: `${org}:${supplierId}`, items: [], next: null, loading: false, error: cause.message }); });
    return () => { current = false; };
  }, [org, document.supplier_id]);
  async function loadMoreRevoked() {
    const supplierId = document.supplier_id, cursor = revokedNext;
    if (!supplierId || !cursor || revokedLoading) return;
    const context = `${org}:${supplierId}`, generation = contractFetchVersion.current;
    setRevokedState(current => ({ ...current, loading: true, error: "" }));
    try {
      const data = await request<ContractHistoryPage>(
        `/organizations/${org}/supplier-contracts?supplier_id=${supplierId}&status=revoked&before_at=${encodeURIComponent(cursor.at)}&before_id=${cursor.id}`,
      );
      const page = checkedHistoryPage(data, org, supplierId);
      if (active.current && supplierContext.current === context && contractFetchVersion.current === generation) {
        setRevokedState(current => ({ context, items: [...current.items,
          ...page.items.filter(row => !current.items.some(existing => existing.id === row.id))],
          next: page.next, loading: false, error: "" }));
      }
    } catch (cause) {
      if (active.current && supplierContext.current === context && contractFetchVersion.current === generation)
        setRevokedState(current => ({ ...current, loading: false,
          error: cause instanceof Error ? cause.message : "Не удалось загрузить историю договоров." }));
    }
  }
  useEffect(() => {
    let current = true;
    void request<OwnedOrder[]>(`/organizations/${org}/purchase-ownership`).then((data) => {
      if (current) setOrders(data.filter((row) => row.kind === "order"));
    }).catch(() => { if (current) setOrderError("Не удалось загрузить подтверждённые заказы. Сохранённые связи накладной сохранены."); });
    return () => { current = false; };
  }, [org]);
  useEffect(() => {
    let current = true;
    void request<Receipt[]>(path).then((data) => { if (current) {
      setRows(data);
      setLoadedKey(listKey);
      const saved = pending.current;
      if (corruptJournal.current) {
        setInitialLoading(false);
        setUncertain(true);
        setRecoveryBlocked(true);
      }
      else if (saved?.org === org) {
        const row = saved.receiptId === null ? null : data.find((item) => item.id === saved.receiptId) ?? null;
        setSelected(row); setSelectedOrg(row ? org : null);
        setDocument(structuredClone(saved.document));
        setEditorOpen(true);
        setUncertain(true);
        const missing = saved.receiptId !== null && row === null;
        setRecoveryBlocked(missing);
        setInitialLoading(false);
        if (missing) setError("Редактируемая накладная не найдена в текущем реестре. Повтор сохранения остаётся заблокирован до восстановления источника.");
      }
      else if (initialReceipt !== undefined && !initialOpened.current) {
        initialOpened.current = true;
        setInitialLoading(false);
        const row = data.find(row => String(row.id) === initialReceipt);
        if (row) {
          setSelected(row); setSelectedOrg(org); setDocument(structuredClone(row.revisions.at(-1)!.document));
          setEditorOpen(true);
          pending.current = null; setUncertain(false); setError(""); setNotice("");
        }
        else setError("Накладная из ссылки не найдена в выбранном юрлице.");
      }
    } }).catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [path, listKey, initialReceipt, org]);
  useEffect(() => {
    if (!selected?.correction_of) {
      setCorrectionReadiness({ context: "", status: "idle" });
      return;
    }
    const context = correctionContext;
    if (selectedOrg !== org) {
      setCorrectionReadiness({ context, status: "error" });
      return;
    }
    let current = true;
    setCorrectionReadiness({ context, status: "loading" });
    void request<unknown>(`/organizations/${org}/receipt-documents/${selected.id}/correction-readiness`)
      .then((data) => {
        if (!current || correctionContextRef.current !== context) return;
        const checked = checkedCorrectionReadiness(data, org, selected);
        setCorrectionReadiness({ context, status: "ready", data: checked });
      })
      .catch(() => {
        if (current && correctionContextRef.current === context)
          setCorrectionReadiness({ context, status: "error" });
      });
    return () => { current = false; };
  }, [org, selectedOrg, selected, correctionContext]);
  useEffect(() => {
    const receipt = selected;
    const context = correctionContext;
    if (!receipt?.correction_of || selectedOrg !== org || correctionReadiness.context !== context
      || correctionReadiness.status !== "ready") {
      setInboundVatEvidence({ context, status: "idle" });
      return;
    }
    let current = true;
    setInboundVatEvidence({ context, status: "loading" });
    void Promise.all(evidenceKinds.map(async ({ kind }) => {
      const value = await accountingRequest<unknown>(evidenceScopePath(org, receipt, kind));
      return [kind, checkedEvidenceList(value, org, receipt, kind)] as const;
    })).then((entries) => {
      if (!current || correctionContextRef.current !== context) return;
      setInboundVatEvidence({ context, status: "ready", files: Object.fromEntries(entries) as Record<InboundVatEvidenceKind, InboundVatEvidenceFile[]> });
      evidenceMessageContext.current = context;
      setEvidenceMessage("");
    }).catch(() => {
      if (current && correctionContextRef.current === context)
        setInboundVatEvidence({ context, status: "error" });
    });
    return () => { current = false; };
  }, [org, selectedOrg, selected, correctionContext, correctionReadiness.context, correctionReadiness.status]);
  useEffect(() => {
    evidenceUploadEpoch.current += 1;
    evidenceMessageContext.current = correctionContext;
    setEvidenceBusy(null);
    setEvidenceForms({
      supplier_eschf_xml: { file: null, reference: "", tax_period: "", evidence: "" },
      supporting_document_pdf: { file: null, reference: "", tax_period: "", evidence: "" },
    });
    setEvidenceMessage("");
  }, [correctionContext, selected]);
  useEffect(() => {
    workpaperEpoch.current += 1;
    setWorkpaperTaxPeriod("");
    setWorkpaperReviewerEvidence("");
    setWorkpaperPreview({ scope: "", evidence_digest: "", status: "idle", error: "" });
    setWorkpaperHistory({ scope: "", status: "idle", items: [], error: "" });
    setPendingWorkpaper(null);
    setWorkpaperJournalError("");
    setWorkpaperMessage("");
    setWorkpaperBusy(null);
  }, [correctionContext]);
  useEffect(() => { workpaperCardEpoch.current += 1; }, [correctionContext]);
  useEffect(() => {
    if (!selected?.correction_of || selectedOrg !== org || inboundVatEvidence.context !== correctionContext
      || inboundVatEvidence.status !== "ready" || !inboundVatEvidence.files || workpaperTaxPeriod) return;
    const currentPeriods = [...new Set(Object.values(inboundVatEvidence.files)
      .flatMap((history) => history.at(-1) ? [history.at(-1)!.tax_period] : []))];
    if (currentPeriods.length === 1 && taxPeriodPattern.test(currentPeriods[0])) {
      workpaperEpoch.current += 1;
      setWorkpaperTaxPeriod(currentPeriods[0]);
    }
  }, [org, selected, selectedOrg, correctionContext, inboundVatEvidence.context,
    inboundVatEvidence.status, inboundVatEvidence.files, workpaperTaxPeriod]);
  useEffect(() => { workpaperEpoch.current += 1; setWorkpaperBusy(null); }, [workpaperScope]);
  const showNextPendingWorkpaper = useCallback((receipt: Receipt): { key: string } | null => {
    let journals: ReturnType<typeof pendingWorkpaperJournalsForReceipt>;
    try { journals = pendingWorkpaperJournalsForReceipt(org, receipt.id); }
    catch {
      setPendingWorkpaper(null);
      setWorkpaperJournalError("Не удалось проверить оставшиеся журналы рабочей ведомости; новая версия заблокирована.");
      return { key: "журнал недоступен" };
    }
    const journal = journals[0];
    if (!journal) {
      setPendingWorkpaper(null);
      setWorkpaperJournalError("");
      return null;
    }
    try {
      if (!journal.receipt_version || !journal.tax_period) throw new Error("Ключ не содержит корректную версию и налоговый период.");
      const journalReceipt = journal.receipt_version === receipt.version
        ? receipt : receiptAtWorkpaperVersion(receipt, journal.receipt_version);
      const command = readPendingWorkpaper(org, journalReceipt, journal.tax_period);
      if (!command) throw new Error("Точный запрос не найден по ключу.");
      setPendingWorkpaper(command);
      setWorkpaperJournalError(`Остался несверенный запрос рабочей ведомости ${journal.key}; сохранение и переход заблокированы.`);
    } catch (cause) {
      setPendingWorkpaper(null);
      const detail = cause instanceof Error ? cause.message : "формат запроса не подтверждён";
      setWorkpaperJournalError(`Оставшийся журнал ${journal.key} нельзя безопасно сверить: ${detail}. Он сохранён, новая версия заблокирована.`);
    }
    return { key: journal.key };
  }, [org]);
  useEffect(() => {
    const receipt = selected;
    const scope = workpaperScope;
    const taxPeriod = workpaperTaxPeriod;
    if (!receipt?.correction_of || selectedOrg !== org || correctionReadinessForSelection.status !== "ready"
      || correctionReadinessForSelection.context !== correctionContext || !taxPeriodPattern.test(taxPeriod)) {
      setWorkpaperHistory({ scope, status: "idle", items: [], error: "" });
      return;
    }
    const epoch = workpaperEpoch.current;
    const requestId = ++workpaperHistoryRequest.current;
    let current = true;
    setWorkpaperHistory({ scope, status: "loading", items: [], error: "" });
    const query = new URLSearchParams({ receipt_id: String(receipt.id), receipt_version: String(receipt.version), tax_period: taxPeriod });
    void accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers?${query.toString()}`)
      .then((data) => workpaperHistoryChain(data, org, receipt, taxPeriod))
      .then((items) => {
        if (!current || requestId !== workpaperHistoryRequest.current || epoch !== workpaperEpoch.current
          || workpaperScopeRef.current !== scope) return;
        setWorkpaperHistory({ scope, status: "ready", items, error: "" });
      })
      .catch((cause: Error & { status?: number }) => {
        if (!current || requestId !== workpaperHistoryRequest.current || epoch !== workpaperEpoch.current
          || workpaperScopeRef.current !== scope) return;
        setWorkpaperHistory({ scope, status: "error", items: [], error: cause.status === 403
          ? `Доступ к истории рабочей ведомости запрещён (403): ${cause.message}` : cause.message });
      });
    return () => { current = false; };
  }, [org, selected, selectedOrg, correctionContext, correctionReadinessForSelection.context,
    correctionReadinessForSelection.status, workpaperScope, workpaperTaxPeriod, workpaperHistoryReload]);
  useEffect(() => {
    const receipt = selected;
    const scope = workpaperScope;
    const taxPeriod = workpaperTaxPeriod;
    if (!receipt?.correction_of || selectedOrg !== org) {
      setPendingWorkpaper(null);
      setWorkpaperJournalError("");
      return;
    }
    let journal: ReturnType<typeof pendingWorkpaperJournalForReceipt>;
    try { journal = pendingWorkpaperJournalForReceipt(org, receipt.id); }
    catch {
      setPendingWorkpaper(null);
      setWorkpaperJournalError("Не удалось проверить журнал рабочей ведомости; новая версия заблокирована.");
      return;
    }
    if (journal && journal.receipt_version !== receipt.version) {
      try {
        if (!journal.receipt_version || !journal.tax_period) throw new Error("Ключ не содержит корректную версию и налоговый период.");
        const oldReceipt = receiptAtWorkpaperVersion(receipt, journal.receipt_version);
        const oldCommand = readPendingWorkpaper(org, oldReceipt, journal.tax_period);
        if (!oldCommand) throw new Error("Сохранённый запрос рабочей ведомости не найден.");
        setPendingWorkpaper(oldCommand);
        setWorkpaperJournalError(`Есть несверенный запрос рабочей ведомости версии ${journal.receipt_version}; сверьте его, прежде чем изменять текущую версию.`);
      } catch (cause) {
        setPendingWorkpaper(null);
        setWorkpaperJournalError(cause instanceof Error
          ? `Не удалось подготовить сверку старого запроса: ${cause.message} Новая версия заблокирована.`
          : "Не удалось подготовить сверку старого запроса; новая версия заблокирована.");
      }
      return;
    }
    if (journal && journal.tax_period !== taxPeriod) {
      try {
        if (!journal.tax_period) throw new Error("Ключ не содержит корректный налоговый период.");
        const command = readPendingWorkpaper(org, receipt, journal.tax_period);
        if (!command) throw new Error("Сохранённый запрос рабочей ведомости не найден.");
        setPendingWorkpaper(command);
        setWorkpaperJournalError(`Есть несверенный запрос за период ${journal.tax_period}; сверьте его, прежде чем изменять накладную.`);
      } catch (cause) {
        setPendingWorkpaper(null);
        setWorkpaperJournalError(cause instanceof Error
          ? `Не удалось подготовить сверку старого запроса: ${cause.message} Новая версия заблокирована.`
          : "Не удалось подготовить сверку старого запроса; новая версия заблокирована.");
      }
      return;
    }
    if (correctionReadinessForSelection.status !== "ready"
      || correctionReadinessForSelection.context !== correctionContext || !taxPeriodPattern.test(taxPeriod)) {
      setPendingWorkpaper(null);
      setWorkpaperJournalError("");
      return;
    }
    let command: PendingInboundVatWorkpaper | null;
    try { command = readPendingWorkpaper(org, receipt, taxPeriod); }
    catch (cause) {
      setPendingWorkpaper(null);
      setWorkpaperJournalError(cause instanceof Error ? cause.message : "Журнал рабочей ведомости недоступен.");
      return;
    }
    setPendingWorkpaper(command);
    setWorkpaperJournalError("");
    if (!command) return;
    const epoch = workpaperEpoch.current;
    const lookupId = ++workpaperJournalLookup.current;
    let current = true;
    setWorkpaperBusy("recover");
    setWorkpaperMessage("Проверяю сохранённый ключ подтверждения рабочей ведомости.");
    void accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers/by-request/${command.request_key}`)
      .then((data) => checkedWorkpaperResult(data, org, receipt, taxPeriod, command!.body))
      .then((saved) => {
        if (!current || lookupId !== workpaperJournalLookup.current || epoch !== workpaperEpoch.current
          || workpaperScopeRef.current !== scope) return;
        clearPendingWorkpaper(command!, org, receipt);
        const next = showNextPendingWorkpaper(receipt);
        setWorkpaperMessage(`Подтверждение найдено: сохранена рабочая ведомость № ${saved.workpaper_id}, редакция ${saved.revision}.${next
          ? ` Следующий ключ ${next.key} остаётся заблокированным до сверки.` : " Все журналы этой накладной разрешены."}`);
        setWorkpaperHistoryReload((value) => value + 1);
      })
      .catch((cause: Error & { status?: number }) => {
        if (!current || lookupId !== workpaperJournalLookup.current || epoch !== workpaperEpoch.current
          || workpaperScopeRef.current !== scope) return;
        if (cause.status === 404) setWorkpaperMessage("Ответ не найден по сохранённому ключу. Повтор отправит тот же ключ и точное тело запроса.");
        else setWorkpaperMessage(cause.status === 403
          ? `Доступ к рабочей ведомости запрещён (403): ${cause.message}`
          : `Не удалось сверить сохранённый запрос: ${cause.message}`);
      }).finally(() => {
        if (current && lookupId === workpaperJournalLookup.current && epoch === workpaperEpoch.current
          && workpaperScopeRef.current === scope) setWorkpaperBusy(null);
      });
    return () => { current = false; };
  }, [org, selected, selectedOrg, correctionContext, correctionReadinessForSelection.context,
    correctionReadinessForSelection.status, workpaperScope, workpaperTaxPeriod, showNextPendingWorkpaper]);
  function open(row: Receipt | null) {
    if (pending.current || uncertain) {
      setError("Сначала подтвердите сохранённую попытку той же редакции. Открытие другой накладной сейчас запрещено.");
      return;
    }
    if (workpaperBusy === "confirm" || workpaperBusy === "recover") {
      setError("Дождитесь сверки рабочей ведомости; переход к другой накладной заблокирован.");
      return;
    }
    if (selected?.correction_of && row?.id !== selected.id) {
      try {
        if (pendingWorkpaperJournalForReceipt(org, selected.id)) {
          setError("Сначала сверьте сохранённую рабочую ведомость этой накладной; переход заблокирован.");
          return;
        }
      } catch {
        setError("Не удалось проверить журнал рабочей ведомости; переход к другой накладной заблокирован.");
        return;
      }
    }
    if (!confirmDiscard()) return;
    workpaperCardEpoch.current += 1;
    workpaperEpoch.current += 1;
    setContracts([]); setContractError("");
    setSelected(row); setSelectedOrg(row ? org : null); setDocument(row ? structuredClone(row.revisions.at(-1)!.document) : blank());
    setWorkpaperTaxPeriod("");
    setWorkpaperReviewerEvidence("");
    setEditorOpen(true);
    pending.current = null; setUncertain(false); setError(""); setNotice("");
  }
  function save(closeAfterSave = false) {
    if (selected?.correction_of) {
      let journal: ReturnType<typeof pendingWorkpaperJournalForReceipt>;
      try { journal = pendingWorkpaperJournalForReceipt(org, selected.id); }
      catch {
        setError("Не удалось проверить журнал рабочей ведомости; новая версия заблокирована.");
        return;
      }
      if (journal || workpaperBusy === "confirm" || workpaperBusy === "recover") {
        const older = Boolean(journal?.receipt_version && journal.receipt_version !== selected.version);
        setError(older
          ? `Сохранён запрос рабочей ведомости для версии ${journal?.receipt_version}; сначала сверьте его, новая версия заблокирована.`
          : "Сначала сверьте сохранённую рабочую ведомость; новая версия накладной заблокирована.");
        return;
      }
    }
    if (selected?.posting || busy || uncertain || pending.current) return;
    if (!document.supplier_id || document.supplier_unp == null) {
      setError("Выберите поставщика накладной из справочника."); return;
    }
    if (!document.contract_id && !document.contract_basis?.trim()) {
      setError("Выберите договор из справочника или укажите основание покупки без зарегистрированного договора."); return;
    }
    if (!document.items.length || document.items.some(row => !row.sku_id || !row.sku_title || !row.unit)) {
      setError("Выберите номенклатуру каждой строки накладной из справочника."); return;
    }
    if (!document.warehouse_id || !document.warehouse_title?.trim()) {
      setError("Выберите склад накладной из справочника юрлица."); return;
    }
    let savedDocument: Document;
    try { savedDocument = expectedSavedDocument(document) as Document; }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Проверьте точность сумм и количества."); return; }
    const command: PendingSave = { org, receiptId: selected?.id ?? null, version: selected?.version ?? 0,
      key: crypto.randomUUID(), document: savedDocument, closeAfterSave };
    try { storePendingSave(command); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось сохранить запрос накладной."); return; }
    pending.current = command;
    unknownSave.current = false;
    setRecoveryBlocked(false);
    void submit(command);
  }
  async function submit(command: PendingSave) {
    setBusy(true); setError(""); setNotice("");
    try {
      const target = `/organizations/${command.org}/receipt-documents`;
      const row = await request<Receipt>(command.receiptId ? `${target}/${command.receiptId}` : target, {
        method: command.receiptId ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(command.receiptId
          ? { key: command.key, expected_version: command.version, document: command.document }
          : { key: command.key, document: command.document }),
      });
      const revision = row?.revisions?.at(-1);
      if (!Number.isSafeInteger(row?.id) || row.id < 1 || row.organization_id !== Number(command.org)
        || !Number.isSafeInteger(row.version) || row.status !== "draft" || row.posting !== null
        || row.version !== command.version + 1
        || revision?.version !== row.version || !revision.document
        || (selected?.correction_of && (!row.correction_of
          || row.correction_of.receipt_id !== selected.correction_of.receipt_id
          || row.correction_of.version !== selected.correction_of.version
          || row.correction_of.entry_id !== selected.correction_of.entry_id))
        || canonical(revision.document) !== canonical(expectedSavedDocument(command.document))
        || (command.receiptId ? row.id !== command.receiptId || revision.request_key !== command.key
          : row.key !== command.key)) {
        throw new Error("Сервер не подтвердил сохранённую версию этой накладной. Форма оставлена открытой.");
      }
      if (!active.current) return;
      clearPendingSave(command);
      pending.current = null; unknownSave.current = false; setUncertain(false); setRecoveryBlocked(false);
      setSelected(command.closeAfterSave ? null : row); setSelectedOrg(command.closeAfterSave ? null : org);
      setDocument(command.closeAfterSave ? blank() : structuredClone(revision.document));
      setEditorOpen(!command.closeAfterSave);
      setRows((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      setNotice(`Накладная № ${row.id}: сохранена версия ${row.version}${command.closeAfterSave ? ", форма закрыта" : ""}.`);
    } catch (e) { if (active.current) {
      const status = (e as Error & { status?: number }).status;
      if (status === undefined || status >= 500) {
        unknownSave.current = true;
        setUncertain(true);
        setError(`${(e as Error).message} Результат сохранения неизвестен. Повторите подтверждение той же редакции.`);
      } else if (unknownSave.current) {
        setUncertain(true);
        setError(`${(e as Error).message} Предыдущий исход остаётся неизвестным; исходный ключ и форма сохранены, новый документ создавать нельзя.`);
      } else {
        clearPendingSave(command);
        pending.current = null; unknownSave.current = false; setUncertain(false); setRecoveryBlocked(false); setError((e as Error).message);
      }
    } }
    finally { if (active.current) setBusy(false); }
  }
  function retryPending() {
    if (busy || recoveryBlocked || !pending.current || pending.current.org !== org) return;
    void submit(pending.current);
  }
  async function registerContract() {
    if (!document.supplier_id || contractBusy || contractRevokeUncertain || uncertain || !newContract.number.trim()
      || !newContract.title.trim() || !newContract.signed_on || !newContract.evidence.trim()) return;
    const supplierId = document.supplier_id, context = `${org}:${supplierId}`;
    ++contractFetchVersion.current;
    setContractBusy(true); setContractError("");
    try {
      const response = await fetch(`/api/procurement/organizations/${org}/supplier-contracts`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ supplier_id: supplierId, number: newContract.number.trim(),
          title: newContract.title.trim(), signed_on: newContract.signed_on,
          expires_on: newContract.expires_on || null, evidence: newContract.evidence.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось зарегистрировать договор.");
      if (data.organization_id !== Number(org) || data.supplier_id !== supplierId
        || !Number.isSafeInteger(data.id) || data.id < 1 || data.number !== newContract.number.trim()
        || data.title !== newContract.title.trim() || data.signed_on !== newContract.signed_on
        || data.expires_on !== (newContract.expires_on || null) || data.evidence !== newContract.evidence.trim())
        throw new Error("Сервер не подтвердил договор этого юрлица и поставщика.");
      if (active.current && supplierContext.current === context) {
        setContracts(current => [...current.filter(row => row.id !== data.id), data]);
        setDocument(current => current.supplier_id === supplierId
          ? { ...current, contract_id: data.id, contract: data.number, contract_basis: null } : current);
        setNewContract({ number: "", title: "", signed_on: "", expires_on: "", evidence: "" });
      }
    } catch (cause) { if (active.current && supplierContext.current === context) setContractError(cause instanceof Error ? cause.message : "Не удалось зарегистрировать договор."); }
    finally { if (active.current) setContractBusy(false); }
  }
  async function submitContractRevoke(command: PendingContractRevoke) {
    setContractBusy(true); setContractError("");
    try {
      const response = await fetch(`/api/procurement/organizations/${command.org}/supplier-contracts/${command.contractId}/revoke`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: command.key, reason: command.reason }),
      });
      const result = await response.json();
      if (!response.ok) throw Object.assign(new Error(typeof result.detail === "string" ? result.detail : "Не удалось отозвать договор."), { status: response.status });
      if (result.id !== command.contractId || result.organization_id !== Number(command.org)
        || result.supplier_id !== command.supplierId || result.is_active !== false
        || result.deactivation_key !== command.key || result.deactivation_reason !== command.reason
        || !result.deactivated_by || !result.deactivated_at)
        throw new Error("Сервер не подтвердил отзыв выбранного договора. Повторите тот же запрос.");
      if (!active.current) return;
      pendingContractRevoke.current = null;
      setContractRevokeUncertain(false);
      ++contractFetchVersion.current;
      if (supplierContext.current === `${command.org}:${command.supplierId}`) {
        setContracts(current => current.filter(row => row.id !== command.contractId));
        setRevokedState(current => ({ context: `${command.org}:${command.supplierId}`,
          items: [result as SupplierContract, ...(current.context === `${command.org}:${command.supplierId}`
            ? current.items.filter(row => row.id !== command.contractId) : [])],
          next: current.context === `${command.org}:${command.supplierId}` ? current.next : null,
          loading: false, error: "" }));
        setDocument(current => current.supplier_id === command.supplierId && current.contract_id === command.contractId
          ? { ...current, contract_id: null, contract: "", contract_basis: null } : current);
        setContractRevokeReason("");
        setNotice(`Договор № ${result.number} отозван. Выберите действующий договор или укажите основание покупки без договора и сохраните накладную.`);
      }
    } catch (cause) {
      if (!active.current || supplierContext.current !== `${command.org}:${command.supplierId}`) return;
      const status = (cause as Error & { status?: number }).status;
      if (status === undefined || status >= 500) {
        setContractRevokeUncertain(true);
        setContractError(`${(cause as Error).message} Результат отзыва неизвестен; повторите запрос с тем же ключом.`);
      } else {
        pendingContractRevoke.current = null;
        setContractRevokeUncertain(false);
        setContractError((cause as Error).message);
      }
    } finally { if (active.current) setContractBusy(false); }
  }
  function revokeContract() {
    if (!document.supplier_id || !document.contract_id || !contracts.some(row => row.id === document.contract_id)
      || contractBusy || uncertain || contractRevokeUncertain || !contractRevokeReason.trim()) return;
    const command = { org, supplierId: document.supplier_id, contractId: document.contract_id,
      key: crypto.randomUUID(), reason: contractRevokeReason.trim() };
    pendingContractRevoke.current = command;
    void submitContractRevoke(command);
  }
  async function uploadInboundVatEvidence(kind: InboundVatEvidenceKind) {
    const receipt = selected;
    const context = correctionContext;
    const readiness = correctionReadinessForSelection.data;
    const form = evidenceForms[kind];
    if (!receipt?.correction_of || selectedOrg !== org || !vatOnlyEvidenceAllowed(readiness, org, receipt)
      || inboundVatEvidence.context !== context || inboundVatEvidence.status !== "ready" || evidenceBusy) return;
    if (!form.file) { evidenceMessageContext.current = context; setEvidenceMessage("Выберите файл для загрузки."); return; }
    const uploadEpoch = ++evidenceUploadEpoch.current;
    const isCurrentUpload = () => correctionContextRef.current === context
      && evidenceUploadEpoch.current === uploadEpoch;
    try {
      checkedEvidenceUploadFile(form.file, kind);
      if (form.file.name.length > 160) throw new Error("Имя файла не должно превышать 160 символов.");
      if (!form.reference.trim() || form.reference.trim().length > 160) throw new Error("Укажите ссылку или номер документа длиной до 160 символов.");
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(form.tax_period)) throw new Error("Укажите налоговый период в формате ГГГГ-ММ.");
      if (form.evidence.trim().length < 10 || form.evidence.trim().length > 2000) throw new Error("Опишите основание загрузки (от 10 до 2000 символов).");
      const requestKey = crypto.randomUUID();
      if (!secureUuid.test(requestKey)) throw new Error("Браузер не предоставил безопасный UUID; загрузка заблокирована.");
      setEvidenceBusy(kind);
      evidenceMessageContext.current = context;
      setEvidenceMessage("");
      const dataUrl = await readFileDataUrl(form.file);
      if (!dataUrl.startsWith(`data:${form.file.type};base64,`)) throw new Error("Формат выбранного файла не удалось подтвердить.");
      const expectedSha256 = await sha256File(form.file);
      if (!isCurrentUpload() || !vatOnlyEvidenceAllowed(correctionReadinessForSelection.data, org, receipt)) return;
      const previous = inboundVatEvidence.files?.[kind].at(-1) ?? null;
      const payload = {
        request_key: requestKey, receipt_id: receipt.id, receipt_version: receipt.version, kind,
        tax_period: form.tax_period, reference: form.reference.trim(), filename: form.file.name,
        data_url: dataUrl, evidence: form.evidence.trim(), supersedes_id: previous?.file_id ?? null,
      };
      const saved = checkedEvidenceFile(await accountingRequest<unknown>(
        `/organizations/${org}/receipt-correction-evidence-files`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
      ), org, receipt, kind);
      if (saved.request_key !== requestKey || saved.receipt_id !== payload.receipt_id
        || saved.receipt_version !== payload.receipt_version || saved.kind !== kind
        || saved.tax_period !== payload.tax_period || saved.reference !== payload.reference
        || saved.filename !== payload.filename || saved.content_type !== form.file.type
        || saved.size_bytes !== form.file.size || saved.sha256 !== expectedSha256
        || saved.evidence !== payload.evidence || saved.supersedes_id !== payload.supersedes_id
        || saved.is_current !== true)
        throw new Error("Сервис не подтвердил точные реквизиты и SHA-256 загруженного файла.");
      if (!isCurrentUpload()) return;
      const priorFiles = inboundVatEvidence.files?.[kind] ?? [];
      const nextFiles = checkedEvidenceList([
        ...priorFiles.map((row) => ({ ...row, is_current: false })),
        saved,
      ], org, receipt, kind);
      setInboundVatEvidence((state) => state.context === context && state.status === "ready" && state.files
        ? { ...state, files: { ...state.files, [kind]: nextFiles } }
        : state);
      setEvidenceForms((state) => ({ ...state, [kind]: { file: null, reference: "", tax_period: "", evidence: "" } }));
      evidenceMessageContext.current = context;
      setEvidenceMessage("Файл сохранён как доказательство для этой версии исправления. Проверки подписи и фактов не выполнялись.");
    } catch (cause) {
      if (isCurrentUpload()) {
        evidenceMessageContext.current = context;
        setEvidenceMessage(cause instanceof Error ? cause.message : "Не удалось проверить или сохранить файл доказательства.");
      }
    } finally {
      if (isCurrentUpload()) setEvidenceBusy(null);
    }
  }
  function currentWorkpaperEvidence(receipt: Receipt, taxPeriod: string) {
    const readiness = correctionReadinessRef.current;
    if (selectedOrg !== org || readiness.context !== correctionContext || readiness.status !== "ready"
      || !vatOnlyEvidenceAllowed(readiness.data, org, receipt))
      throw new Error("Рабочая ведомость доступна только для точной VAT-only редакции текущего юрлица.");
    return checkedCurrentWorkpaperEvidence(inboundVatEvidenceRef.current, org, receipt, taxPeriod);
  }
  function workpaperRequestIsCurrent(scope: string, epoch: number, evidenceDigest?: string) {
    return active.current && epoch === workpaperEpoch.current && workpaperScopeRef.current === scope
      && (evidenceDigest === undefined || workpaperEvidenceDigestRef.current === evidenceDigest);
  }
  async function previewInboundVatWorkpaper() {
    const receipt = selected;
    const taxPeriod = workpaperTaxPeriod;
    const scope = workpaperScope;
    const epoch = workpaperEpoch.current;
    if (!receipt?.correction_of || !taxPeriodPattern.test(taxPeriod) || workpaperBusy) return;
    try {
      const expectedEvidence = currentWorkpaperEvidence(receipt, taxPeriod);
      const evidenceDigest = workpaperEvidenceDigest;
      setWorkpaperBusy("preview");
      setWorkpaperMessage("");
      setWorkpaperPreview({ scope, evidence_digest: evidenceDigest, status: "loading", error: "" });
      const preview = await accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ receipt_id: receipt.id, receipt_version: receipt.version, tax_period: taxPeriod }),
      });
      const checked = await checkedWorkpaperPreview(preview, org, receipt, taxPeriod, expectedEvidence);
      if (!workpaperRequestIsCurrent(scope, epoch, evidenceDigest)) return;
      setWorkpaperPreview({ scope, evidence_digest: evidenceDigest, status: "ready", data: checked, error: "" });
      setWorkpaperMessage("Предпросмотр привязан к текущей редакции и текущим байтово проверенным доказательствам.");
    } catch (cause) {
      if (!workpaperRequestIsCurrent(scope, epoch)) return;
      const detail = cause instanceof Error ? cause.message : "Не удалось проверить основу рабочей ведомости.";
      const errorMessage = (cause as Error & { status?: number }).status === 403
        ? `Доступ к предпросмотру запрещён (403): ${detail}` : detail;
      setWorkpaperPreview({ scope, evidence_digest: workpaperEvidenceDigestRef.current, status: "error", error: errorMessage });
      setWorkpaperMessage("");
    } finally {
      if (workpaperRequestIsCurrent(scope, epoch)) setWorkpaperBusy(null);
    }
  }
  function acceptSavedWorkpaper(command: PendingInboundVatWorkpaper, saved: InboundVatWorkpaperResult,
    receipt: Receipt, scope: string, epoch: number, requestIsCurrent = () => workpaperRequestIsCurrent(scope, epoch)) {
    if (!requestIsCurrent()) return;
    clearPendingWorkpaper(command, org, receipt);
    const selectedReceipt = selected?.id === receipt.id ? selected : receipt;
    const next = showNextPendingWorkpaper(selectedReceipt);
    setWorkpaperPreview({ scope, evidence_digest: "", status: "idle", error: "" });
    setWorkpaperMessage(`Сохранена рабочая ведомость № ${saved.workpaper_id}, редакция ${saved.revision}, для версии накладной ${command.receipt_version}. Все review-only ограничения остаются включёнными.${next
      ? ` Следующий ключ ${next.key} остаётся заблокированным до сверки.` : " Все журналы этой накладной разрешены."}`);
    setWorkpaperHistoryReload((value) => value + 1);
  }
  async function confirmInboundVatWorkpaper() {
    const receipt = selected;
    const taxPeriod = workpaperTaxPeriod;
    const scope = workpaperScope;
    const epoch = workpaperEpoch.current;
    const preview = workpaperPreview.scope === scope && workpaperPreview.status === "ready"
      ? workpaperPreview.data : undefined;
    const history = workpaperHistory.scope === scope && workpaperHistory.status === "ready"
      ? workpaperHistory.items : undefined;
    if (!receipt?.correction_of || !preview || !history || workpaperBusy || pendingWorkpaper || workpaperJournalError) return;
    try {
      currentWorkpaperEvidence(receipt, taxPeriod);
      if (workpaperPreview.evidence_digest !== workpaperEvidenceDigest)
        throw new Error("Доказательства изменились после предпросмотра. Загрузите актуальный предпросмотр.");
      if (workpaperHistory.status !== "ready") throw new Error("Сначала загрузите и проверьте историю рабочей ведомости.");
      const reviewerEvidence = workpaperReviewerEvidence.trim();
      if (reviewerEvidence.length < 10 || reviewerEvidence.length > 2000)
        throw new Error("Укажите содержательное основание проверки длиной от 10 до 2000 символов.");
      const requestKey = crypto.randomUUID();
      if (!secureUuid.test(requestKey)) throw new Error("Браузер не предоставил безопасный UUID; подтверждение заблокировано.");
      const latest = history.at(-1) ?? null;
      const body: InboundVatWorkpaperConfirmBody = { request_key: requestKey, receipt_id: receipt.id,
        receipt_version: receipt.version, tax_period: taxPeriod, basis_digest: preview.basis_digest,
        reviewer_evidence: reviewerEvidence, supersedes_workpaper_id: latest?.workpaper_id ?? null };
      const bodyJson = JSON.stringify(body);
      const journalKey = workpaperJournalKey(org, receipt.id, receipt.version, taxPeriod);
      if (sessionStorage.getItem(journalKey) !== null) throw new Error("Для этой области уже сохранён неподтверждённый запрос. Сначала сверьте и повторите именно его.");
      const command = storePendingWorkpaper({ organization_id: Number(org), receipt_id: receipt.id,
        receipt_version: receipt.version, tax_period: taxPeriod, request_key: requestKey, body, body_json: bodyJson });
      setPendingWorkpaper(command);
      setWorkpaperBusy("confirm");
      setWorkpaperMessage("Сохраняю неизменяемую рабочую ведомость только для review; проводка и решение о вычете не создаются.");
      try {
        const result = await accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: command.body_json,
        });
        const saved = await checkedWorkpaperResult(result, org, receipt, taxPeriod, body);
        acceptSavedWorkpaper(command, saved, receipt, scope, epoch);
      } catch (cause) {
        if (!workpaperRequestIsCurrent(scope, epoch)) return;
        let recovered: InboundVatWorkpaperResult | null = null;
        let recoveryError: Error & { status?: number } | null = null;
        try {
          const result = await accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers/by-request/${requestKey}`);
          recovered = await checkedWorkpaperResult(result, org, receipt, taxPeriod, body);
        } catch (lookupCause) { recoveryError = lookupCause as Error & { status?: number }; }
        if (!workpaperRequestIsCurrent(scope, epoch)) return;
        if (recovered) acceptSavedWorkpaper(command, recovered, receipt, scope, epoch);
        else {
          setPendingWorkpaper(command);
          const causeMessage = cause instanceof Error ? cause.message : "Сервер не подтвердил ответ.";
          const lookupMessage = recoveryError?.status === 404
            ? "Сохранённая запись пока не найдена по ключу."
            : recoveryError?.status === 403 ? `Проверка ключа запрещена (403): ${recoveryError.message}`
              : recoveryError ? `Не удалось проверить ключ: ${recoveryError.message}` : "";
          setWorkpaperMessage(`${causeMessage} Результат запроса остаётся неизвестным. ${lookupMessage} Повтор используйте только с тем же ключом и телом.`);
        }
      }
    } catch (cause) {
      if (!workpaperRequestIsCurrent(scope, epoch)) return;
      const errorMessage = cause instanceof Error ? cause.message : "Не удалось сохранить запрос рабочей ведомости.";
      setWorkpaperMessage((cause as Error & { status?: number }).status === 403
        ? `Доступ к подтверждению запрещён (403): ${errorMessage}` : errorMessage);
    } finally {
      if (workpaperRequestIsCurrent(scope, epoch)) setWorkpaperBusy(null);
    }
  }
  async function retryPendingInboundVatWorkpaper() {
    const receipt = selected;
    const command = pendingWorkpaper;
    const scope = workpaperScope;
    const epoch = workpaperEpoch.current;
    const cardEpoch = workpaperCardEpoch.current;
    const cardContext = correctionContext;
    if (!receipt?.correction_of || !command || workpaperBusy
      || command.organization_id !== Number(org) || command.receipt_id !== receipt.id
      || command.receipt_version > receipt.version) return;
    let commandReceipt: Receipt;
    try { commandReceipt = receiptAtWorkpaperVersion(receipt, command.receipt_version); }
    catch (cause) {
      setWorkpaperJournalError(cause instanceof Error ? cause.message : "Редакция запроса отсутствует в загруженной истории.");
      return;
    }
    const staleVersion = command.receipt_version < receipt.version;
    const requestIsCurrent = () => staleVersion
      ? active.current && cardEpoch === workpaperCardEpoch.current && correctionContextRef.current === cardContext
      : workpaperRequestIsCurrent(scope, epoch);
    setWorkpaperBusy("recover");
    setWorkpaperMessage(`Сверяю сохранённый запрос для версии ${command.receipt_version} по request key.`);
    try {
      let saved: InboundVatWorkpaperResult | null = null;
      try {
        const existing = await accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers/by-request/${command.request_key}`);
        saved = await checkedWorkpaperResult(existing, org, commandReceipt, command.tax_period, command.body);
      } catch (lookupCause) {
        const lookupError = lookupCause as Error & { status?: number };
        const absent = lookupError.status === 404;
        const retryableCurrentLookup = !staleVersion && lookupError.status !== 403
          && (lookupError.status !== undefined && lookupError.status >= 500
            || lookupCause instanceof TypeError);
        if (!absent && !retryableCurrentLookup) throw lookupCause;
      }
      if (saved) acceptSavedWorkpaper(command, saved, commandReceipt, scope, epoch, requestIsCurrent);
      else {
        try {
          const result = await accountingRequest<unknown>(`/organizations/${org}/inbound-vat-correction-workpapers`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: command.body_json,
          });
          const checked = await checkedWorkpaperResult(result, org, commandReceipt, command.tax_period, command.body);
          acceptSavedWorkpaper(command, checked, commandReceipt, scope, epoch, requestIsCurrent);
        } catch (cause) {
          const failure = cause as Error & { status?: number };
          if (staleVersion && failure.status === 409
            && failure.message === "Workpaper requires the exact current correction draft revision") {
            if (!requestIsCurrent()) return;
            clearPendingWorkpaper(command, org, commandReceipt);
            const next = showNextPendingWorkpaper(receipt);
            setWorkpaperPreview({ scope, evidence_digest: "", status: "idle", error: "" });
            setWorkpaperMessage(`Запрос рабочей ведомости для версии ${command.receipt_version} не создал запись: сервер подтвердил устаревшую редакцию.${next
              ? ` Следующий ключ ${next.key} остаётся заблокированным до сверки.` : ` Новая версия ${receipt.version} разблокирована.`}`);
            return;
          }
          throw cause;
        }
      }
    } catch (cause) {
      if (!requestIsCurrent()) return;
      const errorMessage = cause instanceof Error ? cause.message : "Не удалось сверить сохранённый запрос.";
      setPendingWorkpaper(command);
      if (staleVersion) setWorkpaperJournalError(`Запрос версии ${command.receipt_version} не разрешён; текущая версия остаётся заблокированной.`);
      setWorkpaperMessage((cause as Error & { status?: number }).status === 403
        ? `Доступ к восстановлению запрещён (403): ${errorMessage}`
        : `Рабочая ведомость пока не подтверждена: ${errorMessage}. Сохранённый ключ и тело оставлены без изменений.`);
    } finally {
      if (requestIsCurrent()) setWorkpaperBusy(null);
    }
  }
  const currentWorkpaperPreview = workpaperPreview.scope === workpaperScope
    && workpaperPreview.evidence_digest === workpaperEvidenceDigest && workpaperPreview.status === "ready"
    ? workpaperPreview.data : undefined;
  const currentWorkpaperHistory = workpaperHistory.scope === workpaperScope ? workpaperHistory : null;
  const selectedPendingWorkpaper = pendingWorkpaper && pendingWorkpaper.organization_id === Number(org)
    && pendingWorkpaper.receipt_id === selected?.id ? pendingWorkpaper : null;
  const currentPendingWorkpaper = selectedPendingWorkpaper
    && selectedPendingWorkpaper.receipt_version === selected?.version
    && selectedPendingWorkpaper.tax_period === workpaperTaxPeriod ? selectedPendingWorkpaper : null;
  const workpaperBlocksReceiptEdit = Boolean(selected?.correction_of && workpaperJournalError);
  let currentWorkpaperEvidenceError = "";
  if (selected?.correction_of && taxPeriodPattern.test(workpaperTaxPeriod)
    && inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "ready") {
    try { checkedCurrentWorkpaperEvidence(inboundVatEvidence, org, selected, workpaperTaxPeriod); }
    catch (cause) { currentWorkpaperEvidenceError = cause instanceof Error ? cause.message : "Проверка доказательств НДС завершилась ошибкой."; }
  }
  const workpaperReadinessAllowed = Boolean(selected?.correction_of && selectedOrg === org
    && correctionReadinessForSelection.context === correctionContext && correctionReadinessForSelection.status === "ready"
    && vatOnlyEvidenceAllowed(correctionReadinessForSelection.data, org, selected));
  const workpaperCanPreview = Boolean(workpaperReadinessAllowed && selected?.correction_of
    && taxPeriodPattern.test(workpaperTaxPeriod) && inboundVatEvidence.context === correctionContext
    && inboundVatEvidence.status === "ready" && !currentWorkpaperEvidenceError && workpaperEvidenceDigest
    && !currentPendingWorkpaper && !workpaperJournalError && !workpaperBusy);
  const workpaperCanConfirm = Boolean(workpaperCanPreview && currentWorkpaperPreview
    && currentWorkpaperHistory?.status === "ready" && workpaperReviewerEvidence.trim().length >= 10
    && workpaperReviewerEvidence.trim().length <= 2000);
  if (initialLoading) return <section className="space-y-3 rounded-xl border border-line bg-surface p-4"><p role="status">Загрузка накладной из ссылки…</p>{error && <><p role="alert">{error}</p><Button onClick={() => setReload(value => value + 1)}>Повторить загрузку накладной</Button></>}</section>;
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Реестр первичных накладных</h2>
    <p className="text-sm text-muted">Суммы в BYN по документу поставщика. Сохранение черновика не создаёт проводки и складские движения.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {orderError && <p role="alert">{orderError}</p>}
    <fieldset disabled={busy} className="space-y-3">
      {uncertain && <div className="rounded border border-accent p-3"><p>Форма сохранена до сверки результата. Повтор отправит те же реквизиты и ключ операции.</p><Button disabled={recoveryBlocked || !pending.current} onClick={retryPending}>Повторить подтверждение той же редакции</Button></div>}
      <div className="flex gap-2"><Button variant="secondary" onClick={() => open(null)}>Новая первичная накладная</Button><Button variant="secondary" onClick={() => setReload((v) => v + 1)}>Обновить реестр</Button></div>
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск по номеру, поставщику или дате<Input aria-label="Поиск накладных" value={query} onChange={(e) => setQuery(e.target.value)} /></label><label>Статус накладной<Select aria-label="Статус накладной" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">Все</option><option value="draft">Черновики</option><option value="posted">Проведённые</option></Select></label></div>
      {!listLoaded && !error && <p role="status">Загрузка реестра накладных…</p>}
      {listLoaded && <p className="text-sm text-muted">Показано {visible.length} из {rows.length} накладных выбранного юрлица за все даты.</p>}
      {listLoaded && <ul className="divide-y divide-line">{visible.map((row) => {
        const source = row.revisions.at(-1)!.document;
        return <li key={row.id} className="flex flex-wrap items-center gap-2 py-2">
          <Button variant="secondary" onClick={() => open(row)}>{source.invoice_reference} · {source.document_date} · {source.supplier}</Button>
          <span className="text-sm">{row.correction_of ? "Черновик исправления" : row.posting ? "Проведена" : "Черновик"} · версия {row.version}</span>
          {row.correction_of && <span className="text-sm">К накладной № {row.correction_of.receipt_id}, версия {row.correction_of.version} · проводка № {row.correction_of.entry_id}. Проведение и WMS пока недоступны.</span>}
          {!row.correction_of && row.posting && <Link className="text-sm text-accent underline" href={`/erp/procurement/receipts/posted/${row.posting.entry_id}?org=${org}`}>Открыть проведённую накладную</Link>}
        </li>;
      })}</ul>}
      {listLoaded && !visible.length && <p className="text-sm text-muted">Накладных по выбранному фильтру нет.</p>}
      {selected?.correction_of && <p role="status">Связанный черновик исправления накладной № {selected.correction_of.receipt_id}, версии {selected.correction_of.version}, проводка № {selected.correction_of.entry_id}. Исходная накладная и её проводка не меняются; проведение и передача в WMS заблокированы до отдельного workflow.</p>}
      {selected?.correction_of && <section aria-labelledby="correction-readiness-heading" className="space-y-2 rounded border border-line p-3">
        <h3 id="correction-readiness-heading" className="font-semibold">Проверка исправления</h3>
        <p>Проведение недоступно. Эта проверка показывает различия и не выдаёт разрешение; движение WMS также недоступно.</p>
        {correctionReadinessForSelection.status === "loading" && <p role="status">Загрузка проверки для текущей версии исправления…</p>}
        {correctionReadinessForSelection.status === "error" && <p role="alert">Не удалось подтвердить проверку для выбранного юрлица и версии. Проведение и движение WMS остаются недоступны.</p>}
        {correctionReadinessForSelection.status === "ready" && correctionReadinessForSelection.data && <>
          <dl className="grid gap-2 md:grid-cols-2">
            <div><dt className="font-medium">Физическое изменение / WMS</dt><dd>{correctionReadinessForSelection.data.physical_change
              ? "Изменилось количество или склад. Физическая корректировка требует отдельного процесса; движение WMS недоступно."
              : "Изменение количества или склада не выявлено; движение WMS всё равно недоступно."}</dd></div>
            <div><dt className="font-medium">Стоимость / слой себестоимости</dt><dd>{correctionReadinessForSelection.data.inventory_value_change
              ? "Стоимость изменилась и может повлиять на слой себестоимости; нужна отдельная оценка исправления."
              : "Изменение стоимости и слоя себестоимости не выявлено."}</dd></div>
            <div><dt className="font-medium">НДС / ЭСЧФ</dt><dd>{correctionReadinessForSelection.data.vat_change
              ? "Изменилась ставка, сумма или основание НДС; нужны отдельная сверка НДС и подтверждение по ЭСЧФ."
              : "Изменение реквизитов НДС не выявлено."}</dd></div>
            <div><dt className="font-medium">Первичный документ</dt><dd>{correctionReadinessForSelection.data.primary_document_change
              ? "Изменились реквизиты первичного документа; нужно подтвердить исправленный документ."
              : "Изменение реквизитов первичного документа не выявлено."}</dd></div>
            <div><dt className="font-medium">Дата операции</dt><dd>{correctionReadinessForSelection.data.operation_date_change
              ? "Дата операции изменилась; период учёта исправления нужно определить отдельно."
              : "Изменение даты операции не выявлено."}</dd></div>
          </dl>
          {correctionReadinessForSelection.data.explanation_only && <p>Изменилось только пояснение; складские, стоимостные, налоговые и первичные реквизиты и дата операции не изменились.</p>}
          {correctionReadinessForSelection.data.no_difference && <p>Различий между исходной накладной и исправлением не выявлено.</p>}
          {correctionReadinessForSelection.data.blockers.length > 0 && <div><h4 className="font-medium">Ограничения</h4>
            <ul className="list-disc pl-5">{correctionReadinessForSelection.data.blockers.map((blocker) => <li key={blocker}>{correctionBlockerLabel(blocker)}</li>)}</ul>
          </div>}
        </>}
      </section>}
      {selected?.correction_of && correctionReadinessForSelection.status === "ready" && correctionReadinessForSelection.data && <section aria-labelledby="inbound-vat-evidence-heading" className="space-y-3 rounded border border-line p-3">
        <h3 id="inbound-vat-evidence-heading" className="font-semibold">Документы в подтверждение исправления НДС</h3>
        <p className="text-sm text-muted">Загруженные файлы привязаны к выбранному юрлицу, накладной и текущей версии исправления. Файл сам по себе не подтверждает подлинность подписи или факты документа и не разрешает проведение либо вычет НДС.</p>
        {inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "loading" && <p role="status">Загрузка списка документов по текущей версии…</p>}
        {inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "error" && <p role="alert">Не удалось проверить принадлежность и целостность документов. Просмотр и загрузка доказательств заблокированы.</p>}
        {inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "ready" && inboundVatEvidence.files && evidenceKinds.map(({ kind, title, accept }) => {
          const files = inboundVatEvidence.files![kind];
          const current = files.at(-1) ?? null;
          const form = evidenceForms[kind];
          const canUpload = vatOnlyEvidenceAllowed(correctionReadinessForSelection.data, org, selected)
            && selectedOrg === org && !busy && !uncertain && !evidenceBusy;
          return <div key={kind} className="space-y-2 rounded border border-line p-3">
            <h4 className="font-medium">{title}</h4>
            {!files.length && <p className="text-sm text-muted">Документы этого вида ещё не загружены.</p>}
            {files.map((file, index) => {
              const query = new URLSearchParams({ receipt_id: String(selected.id), receipt_version: String(selected.version), kind });
              return <article key={file.file_id} className="space-y-1 rounded bg-surface p-2 text-sm">
                <p className="font-medium">{file.is_current ? "Текущий файл" : "История"} · {file.filename}</p>
                <p>Основание: {file.reference} · налоговый период {file.tax_period} · {file.size_bytes} байт</p>
                <p className="break-all">SHA-256: {file.sha256}</p>
                <p>Загрузил: {file.actor} · {file.created_at}</p>
                <p>{file.is_current ? "Текущая версия документа" : "Заменён последующим файлом"}{file.supersedes_id ? ` · заменяет файл № ${file.supersedes_id}` : ""}</p>
                <a className="text-accent underline" href={`/api/accounting/organizations/${org}/receipt-correction-evidence-files/${file.file_id}/download?${query.toString()}`}>Открыть файл № {file.file_id}</a>
                {index < files.length - 1 && <span className="sr-only"> Предыдущая запись истории</span>}
              </article>;
            })}
            {vatOnlyEvidenceAllowed(correctionReadinessForSelection.data, org, selected)
              ? <div className="space-y-2 border-t border-line pt-3">
                <p className="text-sm">Загрузка разрешена только для подтверждённого VAT-only изменения. {current ? `Новый файл заменит текущий файл № ${current.file_id}.` : "Это будет первая редакция документа."}</p>
                <label>Ссылка или номер документа<Input aria-label={`Основание документа: ${kind}`} maxLength={160} disabled={!canUpload} value={form.reference} onChange={(event) => setEvidenceForms((state) => ({ ...state, [kind]: { ...state[kind], reference: event.target.value } }))} /></label>
                <label>Налоговый период<Input aria-label={`Налоговый период: ${kind}`} type="month" disabled={!canUpload} value={form.tax_period} onChange={(event) => setEvidenceForms((state) => ({ ...state, [kind]: { ...state[kind], tax_period: event.target.value } }))} /></label>
                <label>Комментарий к загрузке<Input aria-label={`Комментарий к загрузке: ${kind}`} maxLength={2000} disabled={!canUpload} value={form.evidence} onChange={(event) => setEvidenceForms((state) => ({ ...state, [kind]: { ...state[kind], evidence: event.target.value } }))} /></label>
                <label>Файл (до 10 МиБ)<Input aria-label={`Файл доказательства: ${kind}`} type="file" accept={accept} disabled={!canUpload} onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  try {
                    if (file) checkedEvidenceUploadFile(file, kind);
                    evidenceMessageContext.current = correctionContext;
                    setEvidenceMessage("");
                    setEvidenceForms((state) => ({ ...state, [kind]: { ...state[kind], file } }));
                  } catch (cause) {
                    event.target.value = "";
                    setEvidenceForms((state) => ({ ...state, [kind]: { ...state[kind], file: null } }));
                    evidenceMessageContext.current = correctionContext;
                    setEvidenceMessage(cause instanceof Error ? cause.message : "Выбран недопустимый файл.");
                  }
                }} /></label>
                {form.file && <p className="text-sm">{form.file.name} · {form.file.size} байт</p>}
                <Button variant="secondary" disabled={!canUpload || !form.file || !form.reference.trim() || !form.tax_period || form.evidence.trim().length < 10}
                  onClick={() => void uploadInboundVatEvidence(kind)}>{evidenceBusy === kind ? "Загрузка…" : current ? "Загрузить новую редакцию" : "Загрузить документ"}</Button>
              </div>
              : <p className="text-sm text-muted">Загрузка недоступна: требуется точное VAT-only изменение без изменения количества, себестоимости, первичного документа и даты операции. Проведение и складское движение остаются недоступны.</p>}
          </div>;
        })}
        {correctionReadinessForSelection.data && !vatOnlyEvidenceAllowed(correctionReadinessForSelection.data, org, selected)
          && <p className="text-sm text-muted">Проведение и вычет НДС остаются недоступны.</p>}
        {evidenceMessageContext.current === correctionContext && evidenceMessage && <p role="status">{evidenceMessage}</p>}
      </section>}
      {selected?.correction_of && (correctionReadinessForSelection.status === "ready" || selectedPendingWorkpaper || workpaperJournalError) && <section aria-labelledby="inbound-vat-workpaper-heading" className="space-y-3 rounded border border-line p-3">
        <h3 id="inbound-vat-workpaper-heading" className="font-semibold">Рабочая ведомость входного НДС · только review</h3>
        <p className="text-sm text-muted">Ведомость фиксирует проверяемые источники и неизменяемую историю. Подтверждение не проверяет подпись или факты документа, не оценивает право на вычет, не означает принятие бухгалтером и не создаёт проводку.</p>
        <div className="grid gap-3 md:grid-cols-2">
          <label>Налоговый период<Input aria-label="Налоговый период рабочей ведомости" type="month" value={workpaperTaxPeriod}
            onChange={(event) => {
              workpaperEpoch.current += 1;
              setWorkpaperTaxPeriod(event.target.value);
              setWorkpaperReviewerEvidence("");
              setWorkpaperPreview({ scope: "", evidence_digest: "", status: "idle", error: "" });
              setWorkpaperHistory({ scope: "", status: "idle", items: [], error: "" });
              setWorkpaperJournalError("");
              setWorkpaperMessage("");
              setWorkpaperBusy(null);
            }} /></label>
          <label>Основание проверки бухгалтером<Input aria-label="Основание проверки бухгалтером" maxLength={2000}
            value={workpaperReviewerEvidence} onChange={(event) => setWorkpaperReviewerEvidence(event.target.value)} /></label>
        </div>
        {!taxPeriodPattern.test(workpaperTaxPeriod) && <p className="text-sm text-muted">Укажите налоговый период в формате ГГГГ-ММ.</p>}
        {!workpaperReadinessAllowed && <p role="alert">Предпросмотр и подтверждение доступны только при точной VAT-only готовности для выбранных юрлица и редакции. Проведение и движение WMS остаются недоступны.</p>}
        {inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "loading" && <p role="status">Ожидаются текущие документы с проверенными байтами.</p>}
        {inboundVatEvidence.context === correctionContext && inboundVatEvidence.status === "error" && <p role="alert">Список текущих доказательств не проверен; предпросмотр и подтверждение заблокированы.</p>}
        {currentWorkpaperEvidenceError && <p role="alert">{currentWorkpaperEvidenceError}</p>}
        {workpaperJournalError && <p role="alert">{workpaperJournalError}</p>}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={!workpaperCanPreview} onClick={() => void previewInboundVatWorkpaper()}>
            {workpaperBusy === "preview" ? "Проверка основы…" : "Предпросмотр рабочей ведомости"}
          </Button>
          <Button variant="secondary" disabled={!workpaperCanConfirm || workpaperBusy !== null}
            onClick={() => void confirmInboundVatWorkpaper()}>
            {workpaperBusy === "confirm" ? "Сохранение review-only записи…" : "Подтвердить ведомость (только review)"}
          </Button>
          <Button variant="secondary" disabled={workpaperBusy !== null || !taxPeriodPattern.test(workpaperTaxPeriod)}
            onClick={() => setWorkpaperHistoryReload((value) => value + 1)}>Обновить историю ведомостей</Button>
        </div>
        {workpaperPreview.scope === workpaperScope && workpaperPreview.status === "loading" && <p role="status">Проверяю основу по текущим редакциям, проводке, счёту 18 и файлам.</p>}
        {workpaperPreview.scope === workpaperScope && workpaperPreview.status === "error" && <p role="alert">{workpaperPreview.error}</p>}
        {workpaperMessage && <p role={/запрещён|не удалось|не совпадает|не подтверждена|не подтверждает|не найдена|повреждён|ошибка/i.test(workpaperMessage) ? "alert" : "status"}>{workpaperMessage}</p>}
        {currentWorkpaperPreview && <article className="space-y-2 rounded border border-line p-3">
          <h4 className="font-medium">Проверенный предпросмотр · {currentWorkpaperPreview.tax_period}</h4>
          <p>Основа SHA-256: {currentWorkpaperPreview.basis_digest} · строк счёта 18: {currentWorkpaperPreview.source_account_18_line_count} · текущих файлов: {currentWorkpaperPreview.current_evidence_file_count}.</p>
          <p>Байты файлов проверены сервером на момент review: да. Статус: только review; принятие бухгалтером и проведение недоступны.</p>
          <WorkpaperSnapshotDetails snapshot={currentWorkpaperPreview.basis} />
        </article>}
        {selectedPendingWorkpaper && <div className="rounded border border-accent p-3">
          <p role="status">Осталась неподтверждённая попытка для версии {selectedPendingWorkpaper.receipt_version}, периода {selectedPendingWorkpaper.tax_period}, ключ {selectedPendingWorkpaper.request_key}. Сохранение и переход заблокированы до сверки.</p>
          <Button variant="secondary" disabled={workpaperBusy !== null} onClick={() => void retryPendingInboundVatWorkpaper()}>
            {workpaperBusy === "recover" ? "Сверка сохранённого запроса…" : selectedPendingWorkpaper.receipt_version !== selected?.version
              ? `Сверить рабочую ведомость версии ${selectedPendingWorkpaper.receipt_version}` : "Повторить ту же рабочую ведомость"}
          </Button>
        </div>}
        {currentWorkpaperHistory?.status === "loading" && <p role="status">Загрузка неизменяемой истории ведомостей…</p>}
        {currentWorkpaperHistory?.status === "error" && <p role="alert">История ведомостей не подтверждена: {currentWorkpaperHistory.error}</p>}
        {currentWorkpaperHistory?.status === "ready" && <div className="space-y-2">
          <h4 className="font-medium">История рабочих ведомостей · {workpaperTaxPeriod}</h4>
          {!currentWorkpaperHistory.items.length && <p className="text-sm text-muted">Для этой версии и периода сохранённых ведомостей пока нет.</p>}
          {currentWorkpaperHistory.items.map((entry) => <article key={entry.workpaper_id} className="space-y-2 rounded border border-line p-3">
            <h5 className="font-medium">Ведомость № {entry.workpaper_id} · редакция {entry.revision}
              {entry.supersedes_workpaper_id ? ` · заменяет ведомость № ${entry.supersedes_workpaper_id}` : " · первая редакция"}</h5>
            <p>Период {entry.tax_period} · проверил {entry.reviewed_by} · {entry.created_at}</p>
            <p>Основание: {entry.reviewer_evidence}</p>
            <p className="break-all">request key: {entry.request_key} · basis digest: {entry.basis_digest} · snapshot digest: {entry.snapshot_digest}</p>
            <p>Байты доказательств проверены сервером на review: да. Подпись проверена: нет. Факты документа проверены: нет. Право на вычет оценено: нет. Принято бухгалтером: нет. Проведение доступно: нет.</p>
            <WorkpaperSnapshotDetails snapshot={entry.snapshot} />
          </article>)}
        </div>}
      </section>}
      {selected?.posting && <p role="status">Проведена · проводка № {selected.posting.entry_id}. Первичные данные доступны для просмотра.</p>}
      {contractRevokeUncertain && <Button variant="secondary" disabled={contractBusy || pendingContractRevoke.current?.org !== org} onClick={() => { if (pendingContractRevoke.current) void submitContractRevoke(pendingContractRevoke.current); }}>Повторить отзыв договора с тем же ключом</Button>}
      {editorOpen && <fieldset disabled={Boolean(selected?.posting) || busy || uncertain || contractBusy || contractRevokeUncertain} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">{fields.map(([field, label]) => <label key={field}>{label}<Input type={field.endsWith("date") ? "date" : "text"} disabled={field === "contract" && Boolean(document.contract_id)} value={document[field]} onChange={(e) => setDocument({ ...document, [field]: e.target.value })} /></label>)}</div>
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск склада накладной<Input aria-label="Поиск склада накладной" maxLength={100} value={warehouseSearch} onChange={(e) => setWarehouseSearch(e.target.value)} /></label><label>Склад накладной из справочника<Select aria-label="Склад накладной из справочника" value={warehouseSelectionValue} onChange={(e) => {
        if (!e.target.value) { setDocument({ ...document, warehouse: "", warehouse_id: null, warehouse_title: null }); return; }
        const warehouse = warehouseOptions.find((option) => String(option.id) === e.target.value);
        if (warehouse) setDocument({ ...document, warehouse: warehouse.name, warehouse_id: warehouse.id, warehouse_title: warehouse.title });
      }}><option value="">Выберите склад</option>{document.warehouse_id && !exactWarehouse && <option value={`saved:${document.warehouse_id}`}>{document.warehouse} · {document.warehouse_title || "старый снимок"} · ID {document.warehouse_id} (сохранённый)</option>}{warehouseOptions.map((option) => <option key={option.id} value={option.id}>{option.name} · {option.title} · ID {option.id}</option>)}</Select></label></div>
      {warehouseError && <p role="alert">Справочник складов недоступен: {warehouseError}</p>}{selected && !document.warehouse_id && <p>У этой версии нет связи со справочником складов. Выберите склад перед сохранением.</p>}{document.warehouse_id && !exactWarehouse && <p>Проверьте сохранённый снимок склада и выберите актуальную запись из списка.</p>}
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск поставщика<Input aria-label="Поиск поставщика накладной" disabled={contractBusy} maxLength={100} value={supplierSearch} onChange={(e) => { setSupplierSearch(e.target.value); setSupplierOptions([]); setSupplierError(""); setContracts([]); setDocument((current) => ({ ...current, supplier: "", supplier_id: null, supplier_unp: null, contract: "", contract_id: null, contract_basis: null })); }} /></label><label>Поставщик накладной из справочника<Select aria-label="Поставщик накладной из справочника" disabled={contractBusy} value={document.supplier_id ?? ""} onChange={(e) => {
        const supplier = supplierOptions.find((option) => String(option.id) === e.target.value);
        setContracts([]); setContractError("");
        setDocument({ ...document, supplier: supplier?.name ?? "", supplier_id: supplier?.id ?? null, supplier_unp: supplier?.unp ?? null, contract: "", contract_id: null, contract_basis: null });
      }}><option value="">Выберите поставщика</option>{document.supplier_id && !supplierOptions.some((option) => option.id === document.supplier_id) && <option value={document.supplier_id}>{document.supplier} · {document.supplier_unp || "без УНП"} (сохранённый)</option>}{supplierOptions.map((option) => <option key={option.id} value={option.id}>{option.name} · {option.unp || "без УНП"}</option>)}</Select></label></div>
      {supplierError && <p role="alert">Справочник поставщиков недоступен: {supplierError}</p>}{selected && !document.supplier_id && <p>У этой версии нет связи со справочником. Выберите поставщика перед исправлением или проведением.</p>}
      {document.supplier_id && <div className="space-y-2 rounded border border-line p-3">
        <label>Договор поставщика из справочника<Select aria-label="Договор поставщика из справочника" value={document.contract_id ?? ""} onChange={(e) => {
          const contract = contracts.find(row => String(row.id) === e.target.value);
          setDocument({ ...document, contract_id: contract?.id ?? null, contract: contract?.number ?? "", contract_basis: null });
        }}><option value="">Без зарегистрированного договора</option>{document.contract_id && !contracts.some(row => row.id === document.contract_id) && <option value={document.contract_id}>{document.contract} (сохранённый ID {document.contract_id})</option>}{contracts.map(row => <option key={row.id} value={row.id}>{row.number} · {row.title} · ID {row.id}</option>)}</Select></label>
        {!document.contract_id && <label>Основание покупки без зарегистрированного договора<Input aria-label="Основание покупки без зарегистрированного договора" maxLength={500} value={document.contract_basis ?? ""} onChange={(e) => setDocument({ ...document, contract: document.contract || (e.target.value ? "Без договора" : ""), contract_basis: e.target.value || null })} /></label>}
        <p className="text-sm text-muted">Если договор не зарегистрирован, укажите основание исключения. Исторический текст накладной не сопоставляется автоматически.</p>
        {contractError && <p role="alert">Справочник договоров: {contractError}</p>}
        {document.contract_id && contracts.some(row => row.id === document.contract_id) && <div className="space-y-2 rounded border border-line p-2">
          <label>Причина отзыва договора<Input aria-label="Причина отзыва договора" maxLength={500} disabled={contractBusy} value={contractRevokeReason} onChange={e => setContractRevokeReason(e.target.value)} /></label>
          <Button variant="secondary" disabled={contractBusy || !contractRevokeReason.trim()} onClick={revokeContract}>Отозвать выбранный договор</Button>
          <p className="text-sm text-muted">Договор исчезнет из выбора для новых накладных. Сохранённые версии накладных и их проводки останутся неизменными.</p>
        </div>}
        <details><summary>Отозванные договоры поставщика ({revokedContracts.length})</summary>
          {revokedError && <p role="alert">История договоров: {revokedError}</p>}
          {!revokedContracts.length && !revokedError && <p>Отозванных договоров нет.</p>}
          <ul>{revokedContracts.map(row => <li key={row.id} className="border-b border-line py-2">
            <strong>№ {row.number} · {row.title} · ID {row.id}</strong>
            <p>Подписан: {row.signed_on}. Основание регистрации: {row.evidence}.</p>
            <p>Зарегистрировал: {shown(row.created_by)}, {shown(row.created_at)}.</p>
            <p>Отозвал: {shown(row.deactivated_by)}, {shown(row.deactivated_at)}. Причина: {shown(row.deactivation_reason)}.</p>
          </li>)}</ul>
          {revokedNext && <Button variant="secondary" disabled={revokedLoading} onClick={() => void loadMoreRevoked()}>{revokedLoading ? "Загрузка…" : "Показать ещё отозванные договоры"}</Button>}
        </details>
        <details><summary>Зарегистрировать договор поставщика</summary><div className="grid gap-2 md:grid-cols-2">
          <label>Номер нового договора<Input aria-label="Номер нового договора" maxLength={200} value={newContract.number} onChange={e => setNewContract({ ...newContract, number: e.target.value })} /></label>
          <label>Название нового договора<Input aria-label="Название нового договора" maxLength={255} value={newContract.title} onChange={e => setNewContract({ ...newContract, title: e.target.value })} /></label>
          <label>Дата подписания договора<Input aria-label="Дата подписания договора" type="date" value={newContract.signed_on} onChange={e => setNewContract({ ...newContract, signed_on: e.target.value })} /></label>
          <label>Дата окончания договора<Input aria-label="Дата окончания договора" type="date" value={newContract.expires_on} onChange={e => setNewContract({ ...newContract, expires_on: e.target.value })} /></label>
          <label>Основание регистрации договора<Input aria-label="Основание регистрации договора" maxLength={500} value={newContract.evidence} onChange={e => setNewContract({ ...newContract, evidence: e.target.value })} /></label>
        </div><Button variant="secondary" disabled={contractBusy} onClick={() => void registerContract()}>Зарегистрировать договор</Button></details>
      </div>}
      <label>Поиск номенклатуры для строк накладной<Input aria-label="Поиск номенклатуры накладной" value={skuSearch} onChange={(e) => { setSkuSearch(e.target.value); setSkuOptions([]); setSkuError(""); }} /></label>
      {skuError && <p role="alert">Справочник номенклатуры недоступен: {skuError}</p>}
      {document.items.map((row, index) => <fieldset key={index} className="rounded-lg border border-line p-3"><legend>Строка накладной {index + 1}</legend>
        <label>Номенклатура из справочника<Select aria-label={`Номенклатура строки ${index + 1}`} value={row.sku_id ?? ""} onChange={(e) => {
          const sku = skuOptions.find((option) => String(option.id) === e.target.value);
          setDocument({ ...document, items: document.items.map((r, i) => i === index ? { ...r,
            sku_id: sku?.id ?? null, sku_title: sku?.title ?? null, sku: sku?.code ?? "", unit: sku?.unit ?? null,
          } : r) });
        }}><option value="">Выберите товар</option>
          {row.sku_id && !skuOptions.some((option) => option.id === row.sku_id) && <option value={row.sku_id}>{row.sku} · {row.sku_title} · {row.unit} (сохранённый)</option>}
          {skuOptions.map((option) => <option key={option.id} value={option.id}>{option.code} · {option.title} · {option.unit} · ID {option.id}</option>)}
        </Select></label>
        {!row.sku_id && row.sku && <p>Прежняя номенклатура «{row.sku}» не сопоставлена со справочником. Выберите товар перед новой редакцией.</p>}
        <label>Заказ поставщику<Select aria-label={`Заказ строки ${index + 1}`} value={row.order_id ?? ""} onChange={(e) => setDocument({ ...document, items: document.items.map((r, i) => i === index ? { ...r, order_id: e.target.value ? Number(e.target.value) : null } : r) })}><option value="">Без связи с заказом</option>{row.order_id && !orders.some((order) => order.source_id === row.order_id) && <option value={row.order_id}>Сохранённый заказ № {row.order_id}</option>}{orders.map((order) => <option key={order.source_id} value={order.source_id}>{order.snapshot.number || `№ ${order.source_id}`} · {order.snapshot.supplier}</option>)}</Select></label>
        <div className="grid gap-3 md:grid-cols-4">{itemFields.map(([field, label]) => <label key={field}>{label}<Input aria-label={`${label} черновика ${index + 1}`} value={row[field] ?? ""} onChange={(e) => setDocument({ ...document, items: document.items.map((r, i) => i === index ? { ...r, [field]: e.target.value } : r) })} /></label>)}</div>
        <Button variant="secondary" disabled={document.items.length === 1} onClick={() => setDocument({ ...document, items: document.items.filter((_, i) => i !== index) })}>Удалить строку {index + 1}</Button></fieldset>)}
      <div className="flex gap-2"><Button variant="secondary" disabled={document.items.length >= 300} onClick={() => setDocument({ ...document, items: [...document.items, item()] })}>Добавить строку накладной</Button><Button disabled={workpaperBlocksReceiptEdit} onClick={() => void save()}>{selected ? `Сохранить исправление версии ${selected.version}` : "Сохранить первичную накладную"}</Button><Button variant="secondary" disabled={workpaperBlocksReceiptEdit} onClick={() => void save(true)}>Сохранить и закрыть</Button></div>
      </fieldset>}
    </fieldset>
    {selected && !selected.posting && !selected.correction_of && (uncertain ? <p>Сначала подтвердите исход сохранения этой редакции. Проведение и складская приёмка заблокированы.</p> : dirty ? <p>Сохраните изменения накладной перед расчётом проводок.</p> : !document.supplier_id ? <p>Сопоставьте поставщика со справочником перед проведением.</p> : document.items.some(row => !row.sku_id) ? <p>Сопоставьте все товары накладной со справочником перед проведением.</p> : <ProcurementReceiptPosting key={`${selected.id}/${selected.version}/${date}/${policyId}`} blocked={busy} org={org} receiptId={selected.id} version={selected.version} items={document.items} accounts={accounts} policyId={policyId} date={date} onBusy={(value) => { if (active.current) setBusy(value); }} onPosted={(entryId) => {
      if (!active.current) return;
      setSelected((current) => current?.id === selected.id ? { ...current, status: "posted", posting: { entry_id: entryId, version: selected.version } } : current);
      setRows((current) => current.map((row) => row.id === selected.id ? { ...row, status: "posted", posting: { entry_id: entryId, version: selected.version } } : row));
      setReload((value) => value + 1); onPosted?.();
    }} />)}
    {selected && !selected.correction_of && !uncertain && !dirty && document.supplier_id && document.items.every(row => row.sku_id) && <Link className="text-accent underline" href={`/erp/wms/receipts/from-primary?org=${org}&receipt=${selected.id}&version=${selected.version}`}>Подготовить складскую приёмку</Link>}
    {selected && <details><summary>История накладной № {selected.id}</summary>{selected.revisions.map((row, index) => {
      const changes = index ? revisionChanges(selected.revisions[index - 1].document, row.document) : [];
      return <article key={row.version} className="border-b border-line py-3">
        <h3>Версия {row.version} · {row.actor} · {row.created_at}</h3>
        {index ? <div><h4>Изменения редакции</h4>{changes.length
          ? <ul>{changes.map((change, i) => <li key={`${change.label}:${i}`}>{change.label}: было «{change.before}», стало «{change.after}».</li>)}</ul>
          : <p>Реквизиты не изменились.</p>}</div> : <p>Исходная редакция.</p>}
        <details><summary>Полный снимок версии {row.version}</summary>
          <dl>{fields.map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{row.document[field]}</dd></div>)}<div><dt>Поставщик накладной</dt><dd>{row.document.supplier} · {row.document.supplier_unp || "УНП не указан"} · {row.document.supplier_id ? `ID ${row.document.supplier_id}` : "связь со справочником неизвестна"}</dd></div><div><dt>Склад накладной</dt><dd>{warehouseSnapshot(row.document)}</dd></div></dl>
          {row.document.items.map((r, i) => <p key={i}>{r.sku} · {r.sku_title || "название неизвестно"} · {r.sku_id ? `SKU ID ${r.sku_id}` : "связь со справочником неизвестна"}{r.order_id ? ` · заказ № ${r.order_id}` : ""} · партия {r.lot} · {r.quantity} {r.unit ?? "(единица не указана)"} · без НДС {r.net_amount} BYN · НДС {r.vat_rate}% / {r.vat_amount} BYN · {r.vat_basis}</p>)}
        </details>
      </article>;
    })}</details>}
  </section>;
}
