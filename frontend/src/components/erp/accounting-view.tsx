"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";
import { searchAccountingBuyers, type AccountingBuyer } from "@/lib/accounting-buyers";
import { searchAccountingContracts, type AccountingContract } from "@/lib/accounting-contracts";
import { searchAccountingEmployees, type AccountingEmployee } from "@/lib/accounting-employees";
import { searchAccountingProductionOrders, type AccountingProductionOrder } from "@/lib/accounting-orders";
import { searchAccountingSettlementDocuments, type AccountingSettlementDocument } from "@/lib/accounting-settlement-documents";
import { searchAccountingSkus, type AccountingSku } from "@/lib/accounting-skus";
import { searchAccountingWarehouses, type AccountingWarehouse } from "@/lib/accounting-warehouses";

import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { AccountingCurrencyFields, type CurrencyFields } from "./accounting-currency-fields";
import { downloadTrialBalance, type ExportTrial } from "./accounting-export";
import { AccountingReconciliation } from "./accounting-reconciliation";
import { AccountingInventoryIssue } from "./accounting-inventory-issue";
import { AccountingInputVat } from "./accounting-input-vat";
import { AccountingOutputVat } from "./accounting-output-vat";
import { AccountingForeignTrade } from "./accounting-foreign-trade";
import { AccountingFixedAssets } from "./accounting-fixed-assets";
import { AccountingRepairs } from "./accounting-repairs";
import { AccountingProductionCostSources } from "./accounting-production-cost-sources";
import { AccountingAssemblyEstimate } from "./accounting-assembly-estimate";
import { AccountingShipmentProfit } from "./accounting-shipment-profit";
import { AccountingPayrollAccrualImport } from "./accounting-payroll-accrual-import";
import { AccountingPayrollStatutoryImport } from "./accounting-payroll-statutory-import";
import { AccountingPayrollControl } from "./accounting-payroll-control";
import { AccountingPayrollWorkpaper } from "./accounting-payroll-workpaper";
import { AccountingPayrollRuleSet } from "./accounting-payroll-rule-set";
import { AccountingStatutoryRequirements } from "./accounting-statutory-requirements";
import { AccountingBank } from "./accounting-bank";
import { AccountingBankImport } from "./accounting-bank-import";
import { AccountingSellerProfiles } from "./accounting-seller-profiles";

import { AccountingInvoiceSettlements } from "./accounting-invoice-settlements";
import { AccountingControls } from "./accounting-controls";
import { AccountingSourceLink } from "./accounting-source-link";
import { AccountingShipmentPreview } from "./accounting-shipment-preview";
import { AccountingShipmentPackage } from "./accounting-shipment-package";
import { AccountingFxRevaluation } from "./accounting-fx-revaluation";
import { ExpenseControl } from "./expense-control";
import { AccountingHome, type AccountingDestination } from "./accounting-home";
import { AccountingReportCatalog, type ReportFavoriteState } from "./accounting-report-catalog";
import { AccountingTradeSettlements } from "./accounting-trade-settlements";
import { AccountingAccountActivity, type AccountMovement } from "./accounting-account-activity";

type Organization = { id: number; name: string; unp: string };
type Account = { id: number; code: string; title: string; cash: boolean; category: string; required_dimensions: string[]; currency_tracking: boolean; quantity_tracking: boolean };
type Policy = { id: number; effective_from: string; reference: string; normative_verified: boolean; inventory_method?: "specific" | "fifo" | "weighted_average"; currency_revaluation?: { monetary_accounts: string[]; gain_account: string; loss_account: string; gain_dimensions: Record<string, string>; loss_dimensions: Record<string, string>; reference: string; settlement_allocation?: "proportional_carrying"; settlement_rate_date?: "posting_date" } | null };
type JournalLine = CurrencyFields & { account: string; title?: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string>; cash_activity?: string };
type Posting = { source: string; source_version: number; operation: string; document_date: string; operation_date: string; posting_date: string; policy_id: number; correction_of?: number; rule_version: string; explanation: string; lines: JournalLine[] };
type Preview = { digest: string; explanation: string; lines: JournalLine[]; normative_verified: boolean };
type ManualRevision = { version: number; request_key?: string; actor: string; created_at: string; digest: string; posting: Posting };
type ManualDocument = { id: number; organization_id: number; number: string; source: string; posting_date: string; version: number; status: "draft" | "posted" | "voided"; entry_id: number | null; updated_at: string; void?: { reason: string; actor: string; created_at: string } | null; revisions: ManualRevision[] };
type ManualDocumentList = { organization_id: number; items: Omit<ManualDocument, "revisions">[]; next_before_id: number | null };
type ManualPostReceipt = { document_id: number; document_version: number; entry_id: number; digest: string };
type FixedAssetOption = { id: number; organization_id: number; asset_key: string; digest: string; name: string; inventory_number: string };
type ManualCreateJournal = { organization_id: string; key: string; request_body: string; reviewed_digest: string; close_after_save: boolean };
type ManualCreateRecovery =
  | { status: "checking" }
  | { status: "none" }
  | { status: "pending"; journal: ManualCreateJournal; raw: string }
  | { status: "blocked"; reason: string };
type ManualCreateStoredRecovery = Exclude<ManualCreateRecovery, { status: "checking" }>;
const manualCreateJournalStorageKey = "accounting.manual-document-create.v1";
const fixedAssetDimensionKeys = new Set([
  "asset", "asset_register_id", "asset_digest", "asset_name", "asset_inventory_number",
]);
function fixedAssetDimension(asset: FixedAssetOption): Record<string, string> {
  return {
    asset: asset.asset_key,
    asset_register_id: String(asset.id),
    asset_digest: asset.digest,
    asset_name: asset.name,
    asset_inventory_number: asset.inventory_number,
  };
}
function parseFixedAssets(response: unknown, org: string): FixedAssetOption[] {
  if (!response || typeof response !== "object" || Array.isArray(response)) {
    throw new Error("Реестр основных средств вернул некорректный ответ.");
  }
  const data = response as { organization_id?: unknown; rows?: unknown };
  if (String(data.organization_id) !== org || !Array.isArray(data.rows)) {
    throw new Error("Реестр основных средств не соответствует выбранной организации.");
  }
  return data.rows.map((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Реестр основных средств содержит некорректную запись.");
    }
    const row = value as Record<string, unknown>;
    if (!Number.isSafeInteger(row.id) || Number(row.id) <= 0 || Number(row.id) > 2_147_483_647
        || String(row.organization_id) !== org
        || typeof row.asset_key !== "string" || !row.asset_key.trim()
        || typeof row.digest !== "string" || !/^[a-f0-9]{64}$/.test(row.digest)
        || typeof row.name !== "string" || !row.name.trim()
        || typeof row.inventory_number !== "string" || !row.inventory_number.trim()) {
      throw new Error("Реестр основных средств содержит неполную или чужую запись.");
    }
    return {
      id: Number(row.id), organization_id: Number(row.organization_id),
      asset_key: row.asset_key, digest: row.digest, name: row.name,
      inventory_number: row.inventory_number,
    };
  });
}
type Trial = ExportTrial;
type Movement = AccountMovement;
type Report = { from: string; to: string; organization_id: number; status: string; pending_documents: number; review_items?: { code: string; count: number; message: string }[]; trial_balance: Trial[]; movements: Movement[]; opening_movements: Movement[]; balance: Record<string, string>; pnl: { income: string; expenses: string; profit: string }; cashflow: Record<string, string> };
type EntryChangeLine = CurrencyFields & { account_code: string; side: string; amount: string; dimensions: Record<string, string> };
type EntryDetail = { id: number; operation: string; source: string; explanation: string; posting_date: string; document_date: string; operation_date: string; created_at: string; actor?: string; source_version: number; rule_version: string; correction_of: number | null; lines: (EntryChangeLine & { id: number; account_title: string })[]; corrections?: { id: number; source_version: number; actor: string; created_at: string; posting_date: string }[]; changes?: { fields: { field: string; before: string | number; after: string | number }[]; posting_changed: boolean; before_lines: EntryChangeLine[]; after_lines: EntryChangeLine[] } | null };
const organizationHint = (value: string | undefined) => value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? value : undefined;

const labels: Record<string, string> = { counterparty: "Контрагент", contract: "Договор", settlement_document: "Документ расчётов", warehouse: "Склад", sku: "Номенклатура", lot: "Партия", order: "Заказ", employee: "Сотрудник", asset: "Основное средство", department: "Подразделение", owner: "Владелец", serial: "Серийный номер" };

type AccountingSection = { id: string; label: string; pages: { id: string; label: string }[]; hiddenTabs?: string[] };
const accountingSections: AccountingSection[] = [
  { id: "workspace", label: "Рабочее место", pages: [{ id: "home", label: "Обзор" }] },
  { id: "documents", label: "Документы", pages: [
    { id: "crm-sales", label: "Продажи CRM" }, { id: "inventory-issue", label: "Списание запасов" },
    { id: "entry", label: "Ручная операция" }, { id: "production", label: "Производство" },
    { id: "assembly-estimate", label: "Калькуляция сборки" },
    { id: "repairs", label: "Ремонты" }, { id: "fixed-assets", label: "ОС и амортизация" },
    { id: "sale", label: "Исключение: продажа вне CRM" },
  ], hiddenTabs: ["shipment-preview"] },
  { id: "banking", label: "Банк и платежи", pages: [
    { id: "bank", label: "Банк" }, { id: "bank-import", label: "Импорт выписки" },
    { id: "invoice-settlements", label: "Оплаты счетов" },
  ] },
  { id: "payroll", label: "Зарплата", pages: [
    { id: "payroll-control", label: "Контроль зарплаты" }, { id: "payroll-hr-draft", label: "Черновая ведомость HR" },
    { id: "payroll-workpaper", label: "Расчётный лист" },
    { id: "payroll-rules", label: "Правила расчёта" },
    { id: "payroll-accruals", label: "Начисления зарплаты" }, { id: "payroll-statutory", label: "Удержания и взносы" },
  ] },
  { id: "tax", label: "Налоги и обязательные платежи", pages: [
    { id: "input-vat", label: "Входной НДС" }, { id: "output-vat", label: "Исходящий НДС" },
    { id: "foreign-trade", label: "ВЭД" }, { id: "statutory-requirements", label: "Формы и ставки" },
  ] },
  { id: "reports", label: "Отчёты", pages: [
    { id: "reports", label: "ОСВ и отчёты" }, { id: "trade-settlements", label: "Расчёты 60/62" },
    { id: "reconciliation", label: "Сверка ОСВ" },
    { id: "expenses", label: "Контроль расходов" },
    { id: "shipment-profit", label: "Прибыль по отгрузкам" },
  ] },
  { id: "closing", label: "Закрытие месяца", pages: [
    { id: "controls", label: "Управление книгой" }, { id: "accounts", label: "План счетов" },
    { id: "fx-revaluation", label: "Валюты" },
    { id: "seller-profiles", label: "Реквизиты продавца" },
  ] },
];

function salesOriginal(org: string, reference: string) {
  const match = /^sales:document:([1-9][0-9]*)$/.exec(reference);
  return match && org ? <a className="text-accent underline" href={`/api/sales/organizations/${encodeURIComponent(org)}/documents/${match[1]}/original`} target="_blank" rel="noreferrer">Оригинал документа № {match[1]}</a> : null;
}

async function request<T>(path: string, body?: unknown, method?: "PUT"): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, { method: method ?? (body === undefined ? "GET" : "POST"), headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body), cache: "no-store" });
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error(response.ok
      ? "ERP вернула некорректный ответ. Повторите загрузку."
      : "Бухгалтерия временно недоступна. Повторите загрузку.");
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : undefined;
    throw new Error(detail ?? "Проверьте заполнение полей и права доступа.");
  }
  return data as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function normalizedText(value: unknown, maxLength: number, minLength = 0): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized.length >= minLength && normalized.length <= maxLength ? normalized : null;
}

function normalizedInteger(value: unknown, minimum: number, maximum = Number.MAX_SAFE_INTEGER): number | null {
  const candidate = typeof value === "number" ? value
    : typeof value === "string" && /^\d+$/.test(value.trim()) ? Number(value.trim()) : NaN;
  return Number.isSafeInteger(candidate) && candidate >= minimum && candidate <= maximum ? candidate : null;
}

function normalizedDate(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null;
}

function normalizedDecimal(value: unknown, maxDigits: number, maxPlaces: number, positive = false): string | null {
  if (typeof value !== "string") return null;
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value.trim());
  if (!match) return null;
  const sign = match[1];
  const whole = match[2] ?? "0";
  const fraction = match[3] ?? match[4] ?? "";
  const exponent = Number(match[5] ?? "0");
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 100) return null;
  const coefficient = `${whole}${fraction}`;

  const decimalPosition = whole.length + exponent;
  const digits = coefficient;
  const expandedWhole = decimalPosition <= 0 ? "0"
    : decimalPosition >= digits.length ? `${digits}${"0".repeat(decimalPosition - digits.length)}`
      : digits.slice(0, decimalPosition);
  const expandedFraction = decimalPosition <= 0 ? `${"0".repeat(-decimalPosition)}${digits}`
    : decimalPosition >= digits.length ? "" : digits.slice(decimalPosition);
  const normalizedWhole = expandedWhole.replace(/^0+(?=\d)/, "");
  const normalizedFraction = expandedFraction.replace(/0+$/, "");
  const isZero = /^0+$/.test(normalizedWhole) && !normalizedFraction;
  const wholeDigits = isZero ? 0 : normalizedWhole.length;
  if (wholeDigits + normalizedFraction.length > maxDigits || normalizedFraction.length > maxPlaces) return null;
  if ((sign === "-" && !isZero) || (positive && isZero)) return null;
  return `${!isZero && sign === "-" ? "-" : ""}${normalizedWhole}${normalizedFraction ? `.${normalizedFraction}` : ""}`;
}

function normalizeManualPostingSnapshot(value: unknown): Record<string, unknown> | null {
  const postingKeys = ["source", "source_version", "operation", "document_date", "operation_date",
    "posting_date", "policy_id", "rule_version", "explanation", "lines", "opening", "correction_of"];
  const lineKeys = ["account", "side", "amount", "dimensions", "currency", "original_amount", "rate",
    "rate_scale", "rate_date", "rate_source", "quantity", "cash_activity"];
  if (!isRecord(value) || !hasOnlyKeys(value, postingKeys) || !Array.isArray(value.lines)
    || value.lines.length < 1 || value.lines.length > 1000) return null;

  const source = normalizedText(value.source, 160, 1);
  const sourceVersion = normalizedInteger(value.source_version, 1);
  const operation = normalizedText(value.operation, 60, 1);
  const documentDate = normalizedDate(value.document_date);
  const operationDate = normalizedDate(value.operation_date);
  const postingDate = normalizedDate(value.posting_date);
  const policyId = normalizedInteger(value.policy_id, 1);
  const ruleVersion = normalizedText(value.rule_version, 100, 1);
  const explanation = normalizedText(value.explanation, 1000, 1);
  const opening = value.opening === undefined ? false : value.opening;
  const correctionOf = value.correction_of == null ? null : normalizedInteger(value.correction_of, 1);
  if (source === null || sourceVersion === null || operation === null || documentDate === null
    || operationDate === null || postingDate === null || policyId === null || ruleVersion === null
    || explanation === null || typeof opening !== "boolean"
    || (value.correction_of != null && correctionOf === null)) return null;

  const lines: Record<string, unknown>[] = [];
  for (const rawLine of value.lines) {
    if (!isRecord(rawLine) || !hasOnlyKeys(rawLine, lineKeys)) return null;
    const account = normalizedText(rawLine.account, 32, 1);
    const side = normalizedText(rawLine.side, 10, 1);
    const amount = normalizedDecimal(rawLine.amount, 20, 2);
    const currency = normalizedText(rawLine.currency === undefined ? "BYN" : rawLine.currency, 3, 3);
    const rawDimensions = rawLine.dimensions === undefined ? {} : rawLine.dimensions;
    if (account === null || !/^[0-9]+(?:\.[0-9]+)*$/.test(account)
      || (side !== "debit" && side !== "credit") || amount === null
      || currency === null || !/^[A-Z]{3}$/.test(currency) || !isRecord(rawDimensions)) return null;

    const dimensions: Record<string, string> = {};
    for (const [key, rawValue] of Object.entries(rawDimensions)) {
      const dimension = normalizedText(rawValue, 200, 1);
      if (!key || dimension === null) return null;
      dimensions[key] = dimension;
    }
    const optionalDecimal = (field: "original_amount" | "rate" | "quantity", maxDigits: number, maxPlaces: number, positive: boolean) => {
      const raw = rawLine[field];
      return raw == null ? null : normalizedDecimal(raw, maxDigits, maxPlaces, positive);
    };
    const originalAmount = optionalDecimal("original_amount", 20, 2, false);
    const rate = optionalDecimal("rate", 24, 6, true);
    const quantity = optionalDecimal("quantity", 24, 6, true);
    const rateScale = rawLine.rate_scale == null ? null : normalizedInteger(rawLine.rate_scale, 1, 2_147_483_647);
    const rateDate = rawLine.rate_date == null ? null : normalizedDate(rawLine.rate_date);
    const rateSource = rawLine.rate_source == null ? null : normalizedText(rawLine.rate_source, 200);
    const cashActivity = rawLine.cash_activity == null ? null : normalizedText(rawLine.cash_activity, 20, 1);
    if ((rawLine.original_amount != null && originalAmount === null)
      || (rawLine.rate != null && rate === null)
      || (rawLine.quantity != null && quantity === null)
      || (rawLine.rate_scale != null && rateScale === null)
      || (rawLine.rate_date != null && rateDate === null)
      || (rawLine.rate_source != null && rateSource === null)
      || (rawLine.cash_activity != null && !["operating", "investing", "financing", "internal"].includes(cashActivity ?? ""))) return null;
    if (currency === "BYN" && [rawLine.original_amount, rawLine.rate, rawLine.rate_scale,
      rawLine.rate_date, rawLine.rate_source].some((item) => item != null)) return null;
    if (currency !== "BYN" && (originalAmount === null || rate === null || rateScale === null
      || rateDate === null || !rateSource)) return null;

    lines.push({ account, side, amount, dimensions, currency, original_amount: originalAmount,
      rate, rate_scale: rateScale, rate_date: rateDate, rate_source: rateSource,
      quantity, cash_activity: cashActivity });
  }
  if (operation !== "manual" || opening || ruleVersion !== "manual-v1") return null;
  return { source, source_version: sourceVersion, operation, document_date: documentDate,
    operation_date: operationDate, posting_date: postingDate, policy_id: policyId,
    rule_version: ruleVersion, explanation, lines, opening, correction_of: correctionOf };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function parseManualCreateJournal(raw: string): ManualCreateJournal | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value)
      || Object.keys(value).sort().join(",") !== "close_after_save,key,organization_id,request_body,reviewed_digest"
      || typeof value.organization_id !== "string"
      || !/^[1-9]\d*$/.test(value.organization_id)
      || !Number.isSafeInteger(Number(value.organization_id))
      || Number(value.organization_id) > 2_147_483_647
      || typeof value.key !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.key)
      || typeof value.request_body !== "string"
      || typeof value.reviewed_digest !== "string"
      || !/^[a-f0-9]{64}$/.test(value.reviewed_digest)
      || typeof value.close_after_save !== "boolean") return null;
    const body: unknown = JSON.parse(value.request_body);
    if (!isRecord(body) || Object.keys(body).sort().join(",") !== "key,posting"
      || body.key !== value.key || !normalizeManualPostingSnapshot(body.posting)) return null;
    return {
      organization_id: value.organization_id,
      key: value.key,
      request_body: value.request_body,
      reviewed_digest: value.reviewed_digest,
      close_after_save: value.close_after_save,
    };
  } catch {
    return null;
  }
}

function readManualCreateRecovery(): ManualCreateStoredRecovery {
  if (typeof window === "undefined") return { status: "none" };
  try {
    const raw = window.sessionStorage.getItem(manualCreateJournalStorageKey);
    if (raw === null) return { status: "none" };
    const journal = parseManualCreateJournal(raw);
    return journal
      ? { status: "pending", journal, raw }
      : { status: "blocked", reason: "Журнал ожидающего создания повреждён. Запись сохранена; новую справку создавать нельзя." };
  } catch {
    return { status: "blocked", reason: "Не удалось прочитать журнал текущей вкладки. Создание справки заблокировано." };
  }
}

function matchesManualCreateResult(value: unknown, journal: ManualCreateJournal): value is ManualDocument {
  if (!isRecord(value)) return false;
  const body: unknown = JSON.parse(journal.request_body);
  const expectedPosting = isRecord(body) ? normalizeManualPostingSnapshot(body.posting) : null;
  const id = normalizedInteger(value.id, 1, 2_147_483_647);
  const organizationId = normalizedInteger(value.organization_id, 1, 2_147_483_647);
  const version = normalizedInteger(value.version, 1, 2_147_483_647);
  const number = normalizedText(value.number, 100, 1);
  const source = normalizedText(value.source, 160, 1);
  const postingDate = normalizedDate(value.posting_date);
  const updatedAt = typeof value.updated_at === "string" && Number.isFinite(Date.parse(value.updated_at))
    ? value.updated_at : null;
  const validStatus = value.status === "draft" || value.status === "posted" || value.status === "voided";
  const revisions = value.revisions;
  const entryId = value.entry_id == null ? null : normalizedInteger(value.entry_id, 1, 2_147_483_647);
  if (expectedPosting === null || id === null || organizationId === null
    || String(organizationId) !== journal.organization_id || version === null || number === null
    || source === null || postingDate === null || updatedAt === null || !validStatus
    || !Array.isArray(revisions) || revisions.length !== version
    || (value.entry_id != null && entryId === null)) return false;

  const normalizedRevisions: Record<string, unknown>[] = [];
  for (let index = 0; index < revisions.length; index += 1) {
    const revision = revisions[index];
    if (!isRecord(revision) || revision.version !== index + 1
      || typeof revision.request_key !== "string"
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(revision.request_key)
      || typeof revision.digest !== "string" || !/^[a-f0-9]{64}$/.test(revision.digest)
      || normalizedText(revision.actor, 200, 1) === null
      || typeof revision.created_at !== "string" || !Number.isFinite(Date.parse(revision.created_at))) return false;
    const posting = normalizeManualPostingSnapshot(revision.posting);
    if (posting === null) return false;
    normalizedRevisions.push(posting);
  }
  const firstRevision = revisions[0] as Record<string, unknown>;
  const latestPosting = normalizedRevisions[normalizedRevisions.length - 1];
  const rawVoid = value.void;
  const hasValidVoid = isRecord(rawVoid)
    && normalizedText(rawVoid.reason, 1000, 1) !== null
    && normalizedText(rawVoid.actor, 200, 1) !== null
    && typeof rawVoid.created_at === "string" && Number.isFinite(Date.parse(rawVoid.created_at));
  if (firstRevision.request_key !== journal.key || firstRevision.digest !== journal.reviewed_digest
    || canonicalJson(normalizedRevisions[0]) !== canonicalJson(expectedPosting)
    || latestPosting.source !== source || latestPosting.posting_date !== postingDate
    || (value.status === "draft" && (entryId !== null || rawVoid != null))
    || (value.status === "posted" && (entryId === null || rawVoid != null))
    || (value.status === "voided" && (entryId !== null || !hasValidVoid))) return false;
  return true;
}

function clearExactManualCreateJournal(raw: string): void {
  const storage = window.sessionStorage;
  if (storage.getItem(manualCreateJournalStorageKey) !== raw) {
    throw new Error("Журнал команды изменился. Сохранённая запись оставлена для сверки.");
  }
  storage.removeItem(manualCreateJournalStorageKey);
  if (storage.getItem(manualCreateJournalStorageKey) !== null) {
    throw new Error("Не удалось очистить подтверждённую команду из журнала. Запись оставлена для сверки.");
  }
}

function manualLineSnapshot(line: JournalLine | undefined): string {
  if (!line) return "—";
  const dimensions = Object.entries(line.dimensions ?? {}).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${labels[key] ?? key}: ${value}`).join(", ");
  return `${line.side === "debit" ? "Дт" : "Кт"} ${line.account} · ${line.amount} BYN`
    + (line.quantity == null ? "" : ` · количество ${line.quantity}`)
    + (line.original_amount == null ? "" : ` · валюта ${line.original_amount} ${line.currency ?? "BYN"}`)
    + (line.rate == null ? "" : ` · курс ${line.rate} за ${line.rate_scale ?? 1} на ${line.rate_date ?? "—"} (${line.rate_source ?? "—"})`)
    + (line.cash_activity ? ` · ДДС ${line.cash_activity}` : "")
    + (dimensions ? ` · ${dimensions}` : "");
}

function describeRevision(before: Posting | undefined, after: Posting): string[] {
  if (!before) return ["Создан документ и сохранены проводки."];
  const names: Partial<Record<keyof Posting, string>> = { source: "Основание", source_version: "Версия основания", document_date: "Дата документа", operation_date: "Дата операции", posting_date: "Дата отражения", policy_id: "Учётная политика", correction_of: "Исправляемая операция", explanation: "Содержание" };
  const fields = (Object.keys(names) as (keyof Posting)[])
    .filter((key) => JSON.stringify(before[key] ?? null) !== JSON.stringify(after[key] ?? null))
    .map((key) => `${names[key]}: «${String(before[key] ?? "—")}» → «${String(after[key] ?? "—")}».`);
  const lineChanges = Array.from({ length: Math.max(before.lines.length, after.lines.length) }, (_, index) => index)
    .filter((index) => JSON.stringify(before.lines[index] ?? null) !== JSON.stringify(after.lines[index] ?? null))
    .map((index) => `Строка ${index + 1}: «${manualLineSnapshot(before.lines[index])}» → «${manualLineSnapshot(after.lines[index])}».`);
  return [...fields, ...lineChanges];
}

function CounterpartyDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingBuyer[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingBuyers(org, term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  return <div className="space-y-2 text-sm">
    <p>Контрагент{dimensions.counterparty_id
      ? `: ${dimensions.counterparty} · УНП ${dimensions.counterparty_unp || "—"} · ID ${dimensions.counterparty_id}`
      : dimensions.counterparty ? `: «${dimensions.counterparty}» — старая связь не сопоставлена` : ": не выбран"}</p>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск контрагента строки ${index + 1}`} value={term} disabled={disabled || loading}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }} placeholder="Наименование, УНП или ID" />
      <Button variant="secondary" disabled={disabled || loading || !term.trim()}
        onClick={() => void search()}>Найти контрагента строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={item.id} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({ counterparty_id: String(item.id), counterparty: item.name,
        counterparty_unp: item.unp, counterparty_revision: String(item.revision) }); setOptions([]); }}>
      Выбрать {item.name} · УНП {item.unp || "—"} · ID {item.id}
    </Button>)}
  </div>;
}

function ContractDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingContract[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingContracts(org, dimensions.counterparty_id || "", term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  return <div className="space-y-2 text-sm">
    <p>Договор{dimensions.contract_id
      ? `: ${dimensions.contract} · ${dimensions.contract_title} · ID ${dimensions.contract_source}:${dimensions.contract_id} · версия ${dimensions.contract_version}`
      : dimensions.contract ? `: «${dimensions.contract}» — старая связь не сопоставлена` : ": не выбран"}</p>
    {!dimensions.counterparty_id && <p role="status">Сначала выберите контрагента строки {index + 1}.</p>}
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск договора строки ${index + 1}`} value={term}
      disabled={disabled || loading || !dimensions.counterparty_id}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }}
      placeholder="Номер, название или ID" />
      <Button variant="secondary" disabled={disabled || loading || !dimensions.counterparty_id || !term.trim()}
        onClick={() => void search()}>Найти договор строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={`${item.source}/${item.id}`} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({ contract: item.number, contract_source: item.source,
        contract_id: String(item.id), contract_title: item.title,
        contract_version: String(item.version) }); setOptions([]); }}>
      Выбрать {item.number} · {item.title} · {item.source === "procurement" ? "закупки" : "продажи"} · ID {item.id}
    </Button>)}
  </div>;
}

function SettlementDocumentDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingSettlementDocument[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingSettlementDocuments(
        org, dimensions.counterparty_id || "", term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  return <div className="space-y-2 text-sm">
    <p>Документ расчётов{dimensions.settlement_document_id
      ? `: ${dimensions.settlement_document_number} · ID ${dimensions.settlement_document_source}:${dimensions.settlement_document_id} · версия ${dimensions.settlement_document_version}`
      : dimensions.settlement_document ? `: «${dimensions.settlement_document}» — старая связь не сопоставлена` : ": не выбран"}</p>
    {!dimensions.counterparty_id && <p role="status">Сначала выберите контрагента строки {index + 1}.</p>}
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск документа расчётов строки ${index + 1}`} value={term}
      disabled={disabled || loading || !dimensions.counterparty_id}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }}
      placeholder="Номер накладной, счёта или ID" />
      <Button variant="secondary" disabled={disabled || loading || !dimensions.counterparty_id || !term.trim()}
        onClick={() => void search()}>Найти документ расчётов строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={`${item.source}/${item.id}/${item.version}`} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({ settlement_document: item.reference,
        settlement_document_source: item.source, settlement_document_id: String(item.id),
        settlement_document_number: item.number,
        settlement_document_version: String(item.version) }); setOptions([]); }}>
      Выбрать {item.number} · {item.source === "procurement" ? "закупки" : "продажи"} · ID {item.id} · версия {item.version}
    </Button>)}
  </div>;
}

function SkuDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingSku[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingSkus(org, term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  return <div className="space-y-2 text-sm">
    <p>Номенклатура{dimensions.sku_id
      ? `: ${dimensions.sku} · ${dimensions.sku_title} · ${dimensions.sku_unit} · ID ${dimensions.sku_id}`
      : dimensions.sku ? `: «${dimensions.sku}» — старая связь не сопоставлена` : ": не выбрана"}</p>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск номенклатуры строки ${index + 1}`} value={term} disabled={disabled || loading}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }} placeholder="Код или наименование" />
      <Button variant="secondary" disabled={disabled || loading || !term.trim()}
        onClick={() => void search()}>Найти номенклатуру строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={item.id} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({ sku_id: String(item.id), sku: item.code,
        sku_title: item.title, sku_unit: item.unit }); setOptions([]); }}>
      Выбрать {item.code} · {item.title} · {item.unit} · ID {item.id}
    </Button>)}
  </div>;
}

function WarehouseDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingWarehouse[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingWarehouses(org, term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  return <div className="space-y-2 text-sm">
    <p>Склад{dimensions.warehouse_id
      ? `: ${dimensions.warehouse} · ${dimensions.warehouse_title} · ID ${dimensions.warehouse_id}`
      : dimensions.warehouse ? `: «${dimensions.warehouse}» — старая связь не сопоставлена` : ": не выбран"}</p>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск склада строки ${index + 1}`} value={term} disabled={disabled || loading}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }} placeholder="Код или наименование склада" />
      <Button variant="secondary" disabled={disabled || loading || !term.trim()}
        onClick={() => void search()}>Найти склад строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={item.id} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({ warehouse_id: String(item.id), warehouse: item.name,
        warehouse_title: item.title }); setOptions([]); }}>
      Выбрать {item.name} · {item.title} · ID {item.id}
    </Button>)}
  </div>;
}

function EmployeeDimensionPicker({ org, onDate, index, dimensions, disabled, requiresDepartment, onSelect }: {
  org: string; onDate: string; index: number; dimensions: Record<string, string>;
  disabled: boolean; requiresDepartment: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingEmployee[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingEmployees(org, onDate, term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  const selected = Boolean(dimensions.employee && dimensions.employee_id
    && dimensions.employment_binding_id && dimensions.employee_contract_ref
    && dimensions.employee_binding_revision && dimensions.employee_binding_digest);
  return <div className="space-y-2 text-sm">
    <p>Сотрудник{selected
      ? `: ${dimensions.employee} · договор ${dimensions.employee_contract_ref} · ID ${dimensions.employee_id} · привязка ${dimensions.employment_binding_id}, версия ${dimensions.employee_binding_revision}`
      : dimensions.employee ? `: «${dimensions.employee}» — выберите действующую привязку` : ": не выбран"}</p>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск сотрудника строки ${index + 1}`} value={term} disabled={disabled || loading}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }} placeholder="ФИО, договор или ID" />
      <Button variant="secondary" disabled={disabled || loading || !term.trim()}
        onClick={() => void search()}>Найти сотрудника строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={item.employment_binding_id} variant="ghost" disabled={disabled}
      onClick={() => { onSelect({
        employee: item.employee, employee_id: item.employee_id,
        employment_binding_id: item.employment_binding_id,
        employee_contract_ref: item.employee_contract_ref,
        employee_binding_revision: item.employee_binding_revision,
        employee_binding_digest: item.employee_binding_digest,
        ...(requiresDepartment ? { department: item.department } : {}),
      }); setOptions([]); }}>
      Выбрать {item.employee} · договор {item.employee_contract_ref} · ID {item.employee_id}
    </Button>)}
  </div>;
}

function OrderDimensionPicker({ org, index, dimensions, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const [term, setTerm] = useState("");
  const [options, setOptions] = useState<AccountingProductionOrder[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const lookup = useRef(0);
  useEffect(() => () => { lookup.current += 1; }, []);
  async function search() {
    const token = ++lookup.current;
    setLoading(true); setError(""); setOptions([]);
    try {
      const result = await searchAccountingProductionOrders(org, term);
      if (token === lookup.current) setOptions(result);
    } catch (reason) { if (token === lookup.current) setError((reason as Error).message); }
    finally { if (token === lookup.current) setLoading(false); }
  }
  const selected = dimensions.order_source === "production" && !!dimensions.order_id;
  return <div className="space-y-2 text-sm">
    <p>Заказ производства{selected
      ? `: ${dimensions.order_number} · ${dimensions.order_product} · ${dimensions.order_quantity} шт. · ID ${dimensions.order_id} · этап на дату привязки: ${dimensions.order_stage_at_ownership}`
      : dimensions.order ? `: «${dimensions.order}» — выберите запись из реестра производства` : ": не выбран"}</p>
    <div className="flex flex-wrap gap-2"><Input aria-label={`Поиск производственного заказа строки ${index + 1}`} value={term} disabled={disabled || loading}
      onChange={(event) => { lookup.current += 1; setTerm(event.target.value); setOptions([]); setLoading(false); }} placeholder="Номер, продукт или ID" />
      <Button variant="secondary" disabled={disabled || loading || !term.trim()}
        onClick={() => void search()}>Найти заказ строки {index + 1}</Button></div>
    {error && <p role="alert">{error}</p>}
    {options.map((item) => <Button key={item.order_id} variant="ghost" disabled={disabled}
      onClick={() => { const snapshot: Record<string, string> = { ...item }; onSelect(snapshot); setOptions([]); }}>
      Выбрать {item.order_number} · {item.order_product} · {item.order_quantity} шт. · ID {item.order_id}
    </Button>)}
  </div>;
}

function FixedAssetDimensionPicker({ org, index, dimensions, assets, assetsOrg, loading, error, disabled, onSelect }: {
  org: string; index: number; dimensions: Record<string, string>; assets: FixedAssetOption[];
  assetsOrg: string; loading: boolean; error: string; disabled: boolean;
  onSelect: (snapshot: Record<string, string>) => void;
}) {
  const available = !!org && assetsOrg === org && !error;
  const current = available ? assets.find((asset) => String(asset.id) === dimensions.asset_register_id) : undefined;
  return <div className="space-y-1 text-sm">
    <label className="block">Основное средство строки {index + 1}<Select
      aria-label={`Основное средство строки ${index + 1}`}
      value={current ? String(current.id) : ""}
      disabled={disabled || !available || loading || !!error}
      onChange={(event) => {
        const asset = assets.find((item) => String(item.id) === event.target.value);
        onSelect(asset ? fixedAssetDimension(asset) : {});
      }}>
      <option value="">{loading ? "Загрузка реестра ОС…" : "Выберите основное средство"}</option>
      {available && assets.map((asset) => <option key={asset.id} value={String(asset.id)}>
        {asset.inventory_number} · {asset.name} · {asset.asset_key}
      </option>)}
    </Select></label>
    {current && <p>{current.inventory_number} · {current.name} · ID {current.id}</p>}
    {!current && dimensions.asset_register_id && available
      && <p role="status">Связь сохранённого документа отсутствует в реестре этой организации; выберите запись повторно.</p>}
    {error && <p role="alert">{error}</p>}
    {!loading && !error && available && assets.length === 0
      && <p role="status">В реестре организации пока нет основных средств.</p>}
  </div>;
}

export function AccountingView({ suggestedOrg, suggestedEntry }: { suggestedOrg?: string; suggestedEntry?: string }) {
  const today = new Date().toISOString().slice(0, 10);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [organizationRefresh, setOrganizationRefresh] = useState(0);
  const [organizationError, setOrganizationError] = useState("");
  const [org, setOrg] = useState("");
  const [start, setStart] = useState(`${today.slice(0, 7)}-01`);
  const [end, setEnd] = useState(today);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [accountActivity, setAccountActivity] = useState<Trial | null>(null);
  const [tab, setTab] = useState("home");
  const [reportFavoriteState, setReportFavoriteState] = useState<ReportFavoriteState>({ ids: [], loaded: false });
  const [shipmentSource, setShipmentSource] = useState("");
  const [controlSection, setControlSection] = useState("setup");
  const [controlsBusy, setControlsBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = busy || controlsBusy;
  const [detail, setDetail] = useState<EntryDetail | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [prepared, setPrepared] = useState<Posting | null>(null);
  const [manualDocument, setManualDocument] = useState<ManualDocument | null>(null);
  const [manualDocuments, setManualDocuments] = useState<ManualDocumentList | null>(null);
  const [manualCreateRecovery, setManualCreateRecovery] = useState<ManualCreateRecovery>({ status: "checking" });
  const [fixedAssets, setFixedAssets] = useState<FixedAssetOption[]>([]);
  const [fixedAssetsOrg, setFixedAssetsOrg] = useState("");
  const [fixedAssetsError, setFixedAssetsError] = useState("");
  const [fixedAssetsErrorOrg, setFixedAssetsErrorOrg] = useState("");
  const fixedAssetsLoading = !!org && tab === "entry"
    && fixedAssetsOrg !== org && fixedAssetsErrorOrg !== org;
  const fixedAssetsErrorForOrg = fixedAssetsErrorOrg === org ? fixedAssetsError : "";
  const [manualDirty, setManualDirty] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [operationDate, setOperationDate] = useState(today);
  const [documentDate, setDocumentDate] = useState(today);
  const [economicDate, setEconomicDate] = useState(today);
  const [sourceVersion, setSourceVersion] = useState(1);
  const [correctionOf, setCorrectionOf] = useState("");
  const [source, setSource] = useState("");
  const [explanation, setExplanation] = useState("");
  const [lines, setLines] = useState<JournalLine[]>([{ account: "", side: "debit", amount: "", dimensions: {} }, { account: "", side: "credit", amount: "", dimensions: {} }]);
  const generation = useRef(0);
  const entryGeneration = useRef(0);
  const previewGeneration = useRef(0);
  const appliedSuggestedOrg = useRef<string | undefined>(undefined);
  const openedSuggestedEntry = useRef("");
  const manualListGeneration = useRef(0);
  const fixedAssetsGeneration = useRef(0);
  const saveCommand = useRef<{ fingerprint: string; key: string } | null>(null);
  const postCommand = useRef<{ fingerprint: string; key: string } | null>(null);
  const voidCommand = useRef<{ fingerprint: string; key: string } | null>(null);
  const confirmDiscard = useUnsavedDocumentGuard(tab === "entry" && manualDirty);

  useEffect(() => {
    let active = true;
    request<Organization[]>("/organizations").then((rows) => { if (active) { setOrganizationError(""); setOrganizations(rows); setOrg((current) => {
      if (appliedSuggestedOrg.current !== suggestedOrg) {
        appliedSuggestedOrg.current = suggestedOrg;
        const hint = organizationHint(suggestedOrg);
        if (hint && rows.some((row) => String(row.id) === hint)) return hint;
      }
      return rows.some((row) => String(row.id) === current) ? current : rows[0] ? String(rows[0].id) : "";
    }); } }).catch((e: Error) => { if (active) setOrganizationError(e.message); });
    return () => { active = false; };
  }, [organizationRefresh, suggestedOrg]);

  useEffect(() => {
    const timer = window.setTimeout(() => setManualCreateRecovery(readManualCreateRecovery()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const refresh = useCallback(async () => {
    const token = ++generation.current;
    setReport(null); setAccountActivity(null); setAccounts([]); setPolicies([]); setDetail(null); setPreview(null); setPrepared(null); setError("");
    if (!org) return;
    setBusy(true);
    try {
      const prefix = `/organizations/${org}`;
      const [r, a, p] = await Promise.all([request<Report>(`${prefix}/reports?start=${start}&end=${end}`), request<Account[]>(`${prefix}/accounts?on=${operationDate}`), request<Policy[]>(`${prefix}/policies`)]);
      if (token === generation.current) { setReport(r); setAccounts(a); setPolicies(p); }
    } catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { if (token === generation.current) setBusy(false); }
  }, [org, start, end, operationDate]);

  useEffect(() => {
    const token = ++generation.current;
    if (!org) return;
    const prefix = `/organizations/${org}`;
    void Promise.all([request<Report>(`${prefix}/reports?start=${start}&end=${end}`), request<Account[]>(`${prefix}/accounts?on=${operationDate}`), request<Policy[]>(`${prefix}/policies`)])
      .then(([r, a, p]) => { if (token === generation.current) { setReport(r); setAccounts(a); setPolicies(p); setError(""); } })
      .catch((e: Error) => { if (token === generation.current) { setError(e.message); setReport(null); setAccountActivity(null); } });
    return () => { generation.current += 1; };
  }, [org, start, end, operationDate]);
  useEffect(() => {
    const hint = organizationHint(suggestedOrg);
    const entry = organizationHint(suggestedEntry);
    if (!hint || org !== hint || !entry) return;
    const key = `${hint}/${entry}`;
    if (openedSuggestedEntry.current === key) return;
    openedSuggestedEntry.current = key;
    const token = generation.current;
    const entryToken = ++entryGeneration.current;
    setTab("reports");
    void request<EntryDetail>(`/organizations/${org}/entries/${entry}`)
      .then((result) => { if (token === generation.current && entryToken === entryGeneration.current) setDetail(result); })
      .catch((reason: Error) => { if (token === generation.current && entryToken === entryGeneration.current) setError(reason.message); });
  }, [org, suggestedOrg, suggestedEntry]);
  useEffect(() => {
    const token = ++manualListGeneration.current;
    if (!org || tab !== "entry") return;
    void request<ManualDocumentList>(`/organizations/${org}/manual-documents`)
      .then((result) => { if (token === manualListGeneration.current) setManualDocuments(result); })
      .catch((reason: Error) => { if (token === manualListGeneration.current) setError(reason.message); });
    return () => { manualListGeneration.current += 1; };
  }, [org, tab]);
  useEffect(() => {
    const token = ++fixedAssetsGeneration.current;
    if (!org || tab !== "entry") {
      return () => { fixedAssetsGeneration.current += 1; };
    }
    void request<unknown>(`/organizations/${org}/fixed-assets`)
      .then((response) => {
        if (token !== fixedAssetsGeneration.current) return;
        const rows = parseFixedAssets(response, org);
        setFixedAssets(rows); setFixedAssetsOrg(org); setFixedAssetsError(""); setFixedAssetsErrorOrg("");
      })
      .catch((reason: Error) => {
        if (token === fixedAssetsGeneration.current) {
          setFixedAssetsError(reason.message); setFixedAssetsErrorOrg(org);
        }
      });
    return () => { fixedAssetsGeneration.current += 1; };
  }, [org, tab]);
  async function reloadManualDocuments() {
    if (!org) return;
    const result = await request<ManualDocumentList>(`/organizations/${org}/manual-documents`);
    if (String(result.organization_id) === org) setManualDocuments(result);
  }
  function invalidatePreview() {
    previewGeneration.current += 1; setPreview(null); setPrepared(null);
    if (tab === "entry") { setManualDirty(true); saveCommand.current = null; postCommand.current = null; }
  }
  function loadManualDocument(row: ManualDocument, expectedOrg = org) {
    if (String(row.organization_id) !== expectedOrg || !row.revisions.length) throw new Error("ERP вернула документ другой организации или без истории.");
    const posting = row.revisions[row.revisions.length - 1].posting;
    if (posting.operation !== "manual") throw new Error("ERP вернула документ другого типа.");
    previewGeneration.current += 1;
    setManualDocument(row); setSource(posting.source); setSourceVersion(posting.source_version);
    setCorrectionOf(posting.correction_of == null ? "" : String(posting.correction_of));
    setExplanation(posting.explanation); setDocumentDate(posting.document_date);
    setEconomicDate(posting.operation_date); setOperationDate(posting.posting_date);
    setLines(posting.lines); setPreview(null); setPrepared(null); setManualDirty(false);
    setVoidReason(""); saveCommand.current = null; postCommand.current = null; voidCommand.current = null;
  }
  async function openManualDocument(id: number) {
    if (!confirmDiscard()) return;
    setBusy(true); setError("");
    try {
      const result = await request<ManualDocument>(`/organizations/${org}/manual-documents/${id}`);
      loadManualDocument(result);
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }
  function newManualDocument() {
    if (manualCreateRecovery.status !== "none") return;
    if (!confirmDiscard()) return;
    previewGeneration.current += 1; setManualDocument(null); setSource(""); setSourceVersion(1);
    setCorrectionOf(""); setExplanation("");
    setLines([{ account: "", side: "debit", amount: "", dimensions: {} }, { account: "", side: "credit", amount: "", dimensions: {} }]);
    setPreview(null); setPrepared(null); setManualDirty(false); setError("");
    setVoidReason(""); saveCommand.current = null; postCommand.current = null; voidCommand.current = null;
  }
  function startManualCorrection() {
    if (!manualDocument || manualDocument.status !== "posted" || manualDocument.entry_id == null) return;
    const original = manualDocument.revisions[manualDocument.revisions.length - 1]?.posting;
    if (!original || original.operation !== "manual") {
      setError("ERP не вернула исходную проведённую версию бухгалтерской справки."); return;
    }
    previewGeneration.current += 1;
    setManualDocument(null); setSource(original.source); setSourceVersion(original.source_version + 1);
    setCorrectionOf(String(manualDocument.entry_id)); setExplanation(original.explanation);
    setDocumentDate(today); setEconomicDate(today); setOperationDate(today);
    setLines(original.lines.map((line) => ({
      ...line, amount: "", quantity: undefined, original_amount: undefined, rate: undefined,
      rate_scale: undefined, rate_date: undefined, rate_source: undefined,
      dimensions: { ...line.dimensions },
    })));
    setPreview(null); setPrepared(null); setManualDirty(true); setError("");
    setNotice(`Создано исправление к операции № ${manualDocument.entry_id}. Введите только разницу; исходная справка сохранена без изменений.`);
    setVoidReason(""); saveCommand.current = null; postCommand.current = null; voidCommand.current = null;
  }
  function changeDate(kind: "start" | "end" | "operation", value: string) {
    generation.current += 1; invalidatePreview(); setReport(null); setAccountActivity(null); setDetail(null); setNotice("");
    if (kind === "start") setStart(value);
    else if (kind === "end") setEnd(value);
    else { setAccounts([]); setPolicies([]); setOperationDate(value); }
  }
  function changeLine(index: number, patch: Partial<JournalLine>) { invalidatePreview(); setLines((current) => current.map((line, i) => i === index ? { ...line, ...patch } : line)); }

  async function prepare() {
    const policy = policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0];
    if (!policy) { setError("Сначала утвердите учётную политику организации."); return; }
    const body: Posting = { source, source_version: sourceVersion, correction_of: correctionOf ? Number(correctionOf) : undefined, operation: "manual", document_date: documentDate, operation_date: economicDate, posting_date: operationDate, policy_id: policy.id, rule_version: "manual-v1", explanation, lines };
    const token = generation.current;
    const previewToken = previewGeneration.current;
    setBusy(true); setError(""); setNotice("");
    try { const result = await request<Preview>(`/organizations/${org}/preview`, body); if (token === generation.current && previewToken === previewGeneration.current) { setPreview(result); setPrepared(body); } }
    catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { if (token === generation.current) setBusy(false); }
  }

  async function saveManual(closeAfterSave = false) {
    if (!prepared || !preview || !org || (manualDocument && manualDocument.status !== "draft")) return;
    if (!manualDocument) {
      const stored = readManualCreateRecovery();
      if (stored.status !== "none") {
        setManualCreateRecovery(stored);
        setError(stored.status === "pending"
          ? "Есть незавершённая команда создания. Сначала восстановите её." : stored.reason);
        return;
      }
    }
    const posting = prepared;
    const checked = preview;
    const version = manualDocument?.version ?? 0;
    const fingerprint = `${org}/${manualDocument?.id ?? "new"}/${version}/${checked.digest}`;
    if (saveCommand.current?.fingerprint !== fingerprint) saveCommand.current = { fingerprint, key: crypto.randomUUID() };
    const key = saveCommand.current.key;
    const payload = manualDocument ? { key, expected_version: version, posting } : { key, posting };
    const requestBody = JSON.stringify(payload);
    let journalRaw: string | null = null;
    let journal: ManualCreateJournal | null = null;
    if (!manualDocument) {
      journal = { organization_id: org, key, request_body: requestBody,
        reviewed_digest: checked.digest, close_after_save: closeAfterSave };
      journalRaw = JSON.stringify(journal);
      try {
        const storage = window.sessionStorage;
        if (storage.getItem(manualCreateJournalStorageKey) !== null) {
          const existing = readManualCreateRecovery();
          setManualCreateRecovery(existing);
          throw new Error(existing.status === "pending"
            ? "Есть незавершённая команда создания. Сначала восстановите её."
            : "Журнал создания уже занят или повреждён. Новая справка заблокирована.");
        }
        storage.setItem(manualCreateJournalStorageKey, journalRaw);
        if (storage.getItem(manualCreateJournalStorageKey) !== journalRaw) {
          throw new Error("Браузер не подтвердил сохранение команды. Запрос не отправлен.");
        }
        setManualCreateRecovery({ status: "pending", journal, raw: journalRaw });
      } catch (reason) {
        const inspected = readManualCreateRecovery();
        setManualCreateRecovery(inspected.status === "none"
          ? { status: "blocked", reason: "Не удалось сохранить команду в журнале текущей вкладки. Запрос не отправлен." }
          : inspected);
        setError((reason as Error).message || "Не удалось сохранить команду в журнале текущей вкладки. Запрос не отправлен.");
        return;
      }
    }
    setBusy(true); setError("");
    try {
      const path = `/organizations/${org}/manual-documents${manualDocument ? `/${manualDocument.id}` : ""}`;
      const result = await request<unknown>(path, manualDocument ? payload : requestBody, manualDocument ? "PUT" : undefined);
      if (manualDocument) {
        if (!isRecord(result) || String(result.organization_id) !== org || result.id !== manualDocument.id
          || result.version !== version + 1 || result.status !== "draft"
          || !Array.isArray(result.revisions)
          || result.revisions[result.revisions.length - 1]?.digest !== checked.digest) {
          throw new Error("ERP не подтвердила сохранение этой версии документа. Форма оставлена открытой для сверки.");
        }
      } else if (!journal || !journalRaw || !matchesManualCreateResult(result, journal)) {
        throw new Error("ERP не подтвердила организацию, ключ и точный снимок новой справки. Команда оставлена для восстановления.");
      }
      if (!manualDocument && journalRaw) {
        clearExactManualCreateJournal(journalRaw);
        setManualCreateRecovery({ status: "none" });
      }
      const saved = result as ManualDocument;
      saveCommand.current = null; postCommand.current = null;
      if (!manualDocument && (saved.version !== 1 || saved.status !== "draft")) {
        loadManualDocument(saved, org);
        setTab("entry");
        setNotice(`${saved.number} · после создания загружено текущее состояние, версия ${saved.version}.`);
      } else {
        setManualDocument(saved); setManualDirty(false);
        setNotice(`${saved.number} · версия ${saved.version} сохранена${closeAfterSave ? " и закрыта" : ""}.`);
        if (closeAfterSave) setTab("home");
      }
      try { await reloadManualDocuments(); } catch { /* saved receipt remains authoritative */ }
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function retryManualCreate() {
    if (manualCreateRecovery.status !== "pending") return;
    const { journal, raw } = manualCreateRecovery;
    const current = readManualCreateRecovery();
    if (current.status !== "pending" || current.raw !== raw) {
      setManualCreateRecovery(current);
      setError("Журнал ожидающей команды изменился или недоступен. Запрос не отправлен.");
      return;
    }
    setBusy(true); setError("");
    try {
      const result = await request<unknown>(
        `/organizations/${journal.organization_id}/manual-documents`, journal.request_body,
      );
      if (!matchesManualCreateResult(result, journal)) {
        throw new Error("ERP вернула документ, не совпадающий с организацией, ключом, digest и точным снимком. Команда сохранена для сверки.");
      }
      clearExactManualCreateJournal(raw);
      setManualCreateRecovery({ status: "none" });
      setOrg(journal.organization_id);
      setError("");
      saveCommand.current = null; postCommand.current = null;
      if (journal.close_after_save && result.version === 1 && result.status === "draft") {
        setManualDocument(null); setManualDirty(false); setTab("home");
        setNotice(`${result.number} · версия 1 подтверждена, форма закрыта.`);
      } else {
        loadManualDocument(result, journal.organization_id);
        setTab("entry");
        setNotice(result.version === 1 && result.status === "draft"
          ? `${result.number} · версия 1 восстановлена из подтверждённой команды.`
          : `${result.number} · текущее состояние загружено, версия ${result.version}.`);
      }
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function post(closeAfterPost = false) {
    if (!prepared || !preview || !manualDocument || manualDocument.status !== "draft") return;
    const token = generation.current;
    const checked = preview;
    const documentId = manualDocument.id;
    const documentVersion = manualDocument.version;
    const fingerprint = `${org}/${documentId}/${documentVersion}/${checked.digest}`;
    if (postCommand.current?.fingerprint !== fingerprint) postCommand.current = { fingerprint, key: crypto.randomUUID() };
    const key = postCommand.current.key;
    if (manualDirty || manualDocument.revisions[manualDocument.revisions.length - 1]?.digest !== checked.digest) {
      setError("Сначала сохраните проверенную версию справки, затем подтвердите проведение."); return;
    }
    setBusy(true); setError("");
    try {
      const result = await request<ManualPostReceipt>(`/organizations/${org}/manual-documents/${documentId}/post`, { key, expected_version: documentVersion, digest: checked.digest });
      if (result.document_id !== documentId || result.document_version !== documentVersion
        || !Number.isSafeInteger(result.entry_id) || result.entry_id <= 0 || result.digest !== checked.digest) {
        throw new Error("ERP не подтвердила проведение этой операции. Форма и проверенный пакет оставлены открытыми для сверки.");
      }
      if (token === generation.current) {
        setManualDocument({ ...manualDocument, status: "posted", entry_id: result.entry_id });
        setManualDirty(false); postCommand.current = null;
        await refresh();
        if (closeAfterPost) {
          setTab("reports");
        }
        setNotice(`Операция № ${result.entry_id} проведена${closeAfterPost ? ", форма закрыта" : ""}.`);
        try { await reloadManualDocuments(); } catch { /* posting receipt remains authoritative */ }
      }
    }
    catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function voidManualDocument() {
    if (!manualDocument || manualDocument.status !== "draft" || manualDirty || !voidReason.trim()) return;
    const documentId = manualDocument.id;
    const documentVersion = manualDocument.version;
    const reason = voidReason.trim();
    const fingerprint = `${org}/${documentId}/${documentVersion}/${reason}`;
    if (voidCommand.current?.fingerprint !== fingerprint) voidCommand.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true); setError("");
    try {
      const result = await request<ManualDocument>(`/organizations/${org}/manual-documents/${documentId}/void`, {
        key: voidCommand.current.key, expected_version: documentVersion, reason,
      });
      if (String(result.organization_id) !== org || result.id !== documentId
        || result.version !== documentVersion || result.status !== "voided"
        || result.void?.reason !== reason) {
        throw new Error("ERP не подтвердила аннулирование этой справки. Сверьте её статус в реестре.");
      }
      setManualDocument(result); setManualDirty(false); setPreview(null); setPrepared(null);
      setNotice(`${result.number} аннулирована. Причина и автор сохранены в истории.`);
      voidCommand.current = null;
      try { await reloadManualDocuments(); } catch { /* void receipt remains authoritative */ }
      await refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  async function openEntry(id: number) {
    const token = generation.current;
    const entryToken = ++entryGeneration.current;
    setError("");
    try { const result = await request<EntryDetail>(`/organizations/${org}/entries/${id}`); if (token === generation.current && entryToken === entryGeneration.current) setDetail(result); }
    catch (e) { if (token === generation.current && entryToken === entryGeneration.current) setError((e as Error).message); }
  }

  function openWorkspace(destination: AccountingDestination) {
    if (!confirmDiscard()) return;
    if (["setup", "periods", "inbox", "import"].includes(destination)) { setControlSection(destination); setTab("controls"); }
    else setTab(destination);
  }

  const currentSection = accountingSections.find((section) =>
    section.pages.some((page) => page.id === tab) || section.hiddenTabs?.includes(tab)) ?? accountingSections[0];

  return <div className="min-w-0 w-full space-y-5 p-6 lg:pr-24 text-ink">
    <header><h1 className="text-2xl font-semibold">Бухгалтерия</h1><p className="mt-1 text-sm text-muted">Проводки и регистры по каждому юридическому лицу. Суммы в BYN.</p></header>
    {organizationError && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-300 bg-surface p-3 text-red-700"><span>{organizationError}</span><Button variant="secondary" onClick={() => { setOrganizationError(""); setOrganizationRefresh((value) => value + 1); }}>Повторить список организаций</Button></div>}
    {error && <div role="alert" className="rounded-xl border border-red-300 bg-surface p-3 text-red-700">{error}</div>}
    {manualCreateRecovery.status === "pending" && <section role="status" aria-label="Восстановление создания справки" className="space-y-2 rounded-xl border border-amber-300 bg-surface p-3 text-sm"><p className="font-semibold">Результат создания справки неизвестен · организация {manualCreateRecovery.journal.organization_id}</p><p>Создание и сохранение новой справки заблокированы. Повтор отправит сохранённые ключ и тело команды (digest {manualCreateRecovery.journal.reviewed_digest}).</p><Button variant="secondary" disabled={locked} onClick={() => void retryManualCreate()}>Повторить создание справки</Button></section>}
    {manualCreateRecovery.status === "blocked" && <section role="alert" aria-label="Создание справки заблокировано" className="rounded-xl border border-red-300 bg-surface p-3 text-sm text-red-700">{manualCreateRecovery.reason} Журнал не очищен автоматически.</section>}
    {notice && <p role="status" className="text-money">{notice}</p>}
    <div className="flex flex-wrap gap-4 rounded-xl border border-line bg-surface p-4">
      <label className="min-w-0 basis-64 flex-1 text-sm">Организация<Select className="min-w-0" aria-label="Организация" value={org} disabled={locked} onChange={(e) => { const next = e.target.value; if (next === org || !confirmDiscard()) return; generation.current += 1; setReport(null); setAccountActivity(null); setDetail(null); setPreview(null); setPrepared(null); setManualDocument(null); setManualDocuments(null); setManualDirty(false); setSource(""); setSourceVersion(1); setCorrectionOf(""); setExplanation(""); setNotice(""); setLines([{ account: "", side: "debit", amount: "", dimensions: {} }, { account: "", side: "credit", amount: "", dimensions: {} }]); setOrg(next); }}><option value="">Выберите организацию</option>{organizations.map((o) => <option key={o.id} value={o.id}>{o.name} · {o.unp}</option>)}</Select></label>
      <label className="text-sm">С<Input aria-label="Начало периода" type="date" value={start} disabled={locked} onChange={(e) => changeDate("start", e.target.value)} /></label>
      <label className="text-sm">По<Input aria-label="Конец периода" type="date" value={end} disabled={locked} onChange={(e) => changeDate("end", e.target.value)} /></label>
      <Button variant="secondary" disabled={locked || !org} onClick={() => void refresh()}>Обновить</Button>
    </div>
    {!organizations.length && !organizationError && !error && <p className="rounded-xl border border-line p-5 text-muted">Нет доступных книг. Руководитель создаёт организацию и назначает доступ бухгалтеру.</p>}
    <nav aria-label="Разделы бухгалтерии" className="flex flex-wrap gap-2">{accountingSections.map((section) =>
      <Button key={section.id} disabled={locked} aria-pressed={currentSection.id === section.id} variant={currentSection.id === section.id ? "primary" : "secondary"} onClick={() => { if (section.pages[0].id !== tab && !confirmDiscard()) return; if (section.id === "closing") setControlSection("periods"); setTab(section.pages[0].id); }}>{section.label}</Button>
    )}</nav>
    {currentSection.pages.length > 1 && <nav aria-label={`Страницы раздела ${currentSection.label}`} className="flex flex-wrap gap-2 rounded-xl border border-line bg-surface p-3">{currentSection.pages.map((page) =>
      <Button key={page.id} disabled={locked} aria-pressed={tab === page.id} variant={tab === page.id ? "primary" : "secondary"} onClick={() => { if (page.id === tab || confirmDiscard()) setTab(page.id); }}>{page.label}</Button>
    )}</nav>}
    {tab === "expenses" && <ExpenseControl org={org} onEntry={(id) => void openEntry(id)} />}
    {tab === "crm-sales" && <section aria-label="Продажи из CRM" className="space-y-3 rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Продажа через сделку и отгрузку</h2><p>Счёт и резерв создаются в CRM, товар отгружается со склада по акту. Проводки выручки, НДС и себестоимости бухгалтер готовит по этому акту в очереди документов. Повторно вводить продажу здесь не нужно.</p><div className="flex flex-wrap gap-3"><Link className="text-accent underline" href="/crm/deals">Открыть сделки CRM</Link><Button variant="secondary" disabled={!org} onClick={() => { setControlSection("inbox"); setTab("controls"); }}>Отгрузки, ожидающие проводок</Button></div></section>}
    {tab === "home" && <AccountingHome selected={!!org} pending={report?.pending_documents ?? null} onOpen={openWorkspace} />}
    {tab === "seller-profiles" && <AccountingSellerProfiles org={org} organization={organizations.find((row) => String(row.id) === org)} onBusyChange={setControlsBusy} />}
    {tab === "invoice-settlements" && <AccountingInvoiceSettlements org={org} onBusyChange={setControlsBusy} />}
    {tab === "reconciliation" && <AccountingReconciliation key={org} org={org} start={start} end={end} />}
    {tab === "input-vat" && <AccountingInputVat org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "output-vat" && <AccountingOutputVat org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "foreign-trade" && <AccountingForeignTrade org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "fx-revaluation" && <AccountingFxRevaluation org={org} month={operationDate.slice(0, 7)} date={operationDate} policy={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]} disabled={locked} onEntry={(id) => void openEntry(id)} />}
    {tab === "fixed-assets" && <AccountingFixedAssets org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} onEntry={(id) => void openEntry(id)} disabled={locked} />}
    {tab === "repairs" && <AccountingRepairs org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} onEntry={(id) => void openEntry(id)} disabled={locked} />}
    {tab === "production" && <AccountingProductionCostSources org={org} month={operationDate.slice(0, 7)} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} onChanged={() => { setOrganizationRefresh((value) => value + 1); void refresh(); }} />}
    {tab === "payroll-control" && <AccountingPayrollControl key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} onEntry={(id) => void openEntry(id)} />}
    {tab === "payroll-hr-draft" && <section aria-label="Черновая ведомость HR" className="space-y-3 rounded-xl border border-line bg-surface p-4"><h2 className="text-lg font-semibold">Черновая ведомость HR</h2><p className="text-sm text-muted">В HR можно подготовить расчёт и распечатать листки сотрудников. Черновик пока не связан с выбранным здесь юрлицом и не создаёт бухгалтерские проводки. Для учёта начислений используйте проверенный импорт с основаниями.</p><Link className="text-accent underline" href="/erp/hr/payroll">Открыть черновую ведомость HR</Link></section>}
    {tab === "payroll-workpaper" && <AccountingPayrollWorkpaper key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} disabled={locked} onBusyChange={setControlsBusy} onOpenRules={() => setTab("payroll-rules")} />}
    {tab === "payroll-rules" && <AccountingPayrollRuleSet key={`${org}:${end.slice(0, 7)}`} org={org} month={end.slice(0, 7)} policies={policies} disabled={locked} onBusyChange={setControlsBusy} onOpenRates={() => setTab("statutory-requirements")} />}
    {tab === "payroll-accruals" && <AccountingPayrollAccrualImport org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} />}
    {tab === "payroll-statutory" && <AccountingPayrollStatutoryImport org={org} month={operationDate.slice(0, 7)} policyId={String(policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id || "")} disabled={locked} onEntry={(id) => void openEntry(id)} onLock={setControlsBusy} />}
    {tab === "statutory-requirements" && <AccountingStatutoryRequirements org={org} month={operationDate.slice(0, 7)} disabled={locked} onBusyChange={setControlsBusy} />}
    {tab === "assembly-estimate" && <AccountingAssemblyEstimate org={org} date={operationDate} />}
    {tab === "shipment-profit" && <AccountingShipmentProfit org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {(tab === "inventory-issue" || tab === "sale") && <AccountingInventoryIssue sale={tab === "sale"} key={`${org}/${tab}`} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} inventoryMethod={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.inventory_method} date={operationDate} onDate={(value) => changeDate("operation", value)} onBusyChange={setControlsBusy} onPosted={() => void refresh()} onEntry={(id) => void openEntry(id)} />}
    {tab === "bank" && <AccountingBank key={org} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} date={operationDate} onDate={(value) => changeDate("operation", value)} onPosted={() => void refresh()} />}
    {tab === "bank-import" && <AccountingBankImport key={org} org={org} accounts={accounts} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} date={operationDate} onDate={(value) => changeDate("operation", value)} onPosted={() => void refresh()} onEntry={(id) => void openEntry(id)} />}
    {tab === "shipment-preview" && <AccountingShipmentPreview key={`${org}/${shipmentSource}`} org={org} source={shipmentSource} accounts={accounts} date={operationDate} policyId={policies.filter((p) => p.effective_from <= operationDate).sort((a, b) => b.effective_from.localeCompare(a.effective_from))[0]?.id} disabled={locked} onDate={(value) => changeDate("operation", value)} onPosted={async () => { setNotice("Отгрузка проведена."); await refresh(); }} />}
    {tab === "controls" && <AccountingControls onEntry={id => void openEntry(id)} onShipment={(source) => { setShipmentSource(source); setTab("shipment-preview"); }} key={`${org}/${controlSection}`} org={org} initialSection={controlSection} onBusyChange={setControlsBusy} onChanged={() => { setOrganizationRefresh((v) => v + 1); void refresh(); }} />}
    {busy && <p role="status">Загрузка…</p>}
    {tab === "trade-settlements" && <AccountingTradeSettlements org={org} start={start} end={end} onEntry={(id) => void openEntry(id)} />}
    {tab === "reports" && <AccountingReportCatalog onOpen={setTab} reportReady={!!org && !!report} favoriteState={reportFavoriteState} setFavoriteState={setReportFavoriteState} />}
    {report && tab === "reports" && <>
      <nav aria-label="Отчёты бухгалтерской книги" className="flex flex-wrap gap-3 rounded-xl border border-line bg-surface p-4 text-sm">
        <span className="font-semibold">ОСВ и журнал — открыты здесь</span>
        <Link className="text-accent underline" href="/erp/finance?tab=pnl">Прибыль и убытки</Link>
        <Link className="text-accent underline" href="/erp/finance?tab=dds">Движение денег</Link>
        <Link className="text-accent underline" href="/erp/finance?tab=balance">Баланс</Link>
        <p className="w-full text-muted">Финансовые отчёты строятся по этой же бухгалтерской книге. На открывшейся странице выберите юрлицо и период заново.</p>
      </nav>
      <Button variant="secondary" onClick={() => { try { downloadTrialBalance(report); } catch (e) { setError((e as Error).message); } }}>Скачать ОСВ CSV</Button>
      <p className="text-xs text-muted">CSV содержит показанный отчёт, валютные суммы и количества. При импорте в Excel задайте счетам текстовый формат, суммам — десятичную точку. Сальдо со знаком: плюс — дебет, минус — кредит. Строка report содержит параметры выгрузки; balance — остатки и обороты.</p>
      <p className="text-sm text-muted">{report.status === "closed_periods" ? "Периоды закрыты" : "Предварительные данные"} · Не проведено документов: {report.pending_documents}. Регламентированная отчётность требует отдельной проверки.</p>
      {!!report.review_items?.length && <div role="status" className="rounded-xl border border-amber-300 bg-surface p-3 text-sm"><p className="font-semibold">Отчёт нельзя считать окончательным</p><ul className="mt-1 list-disc pl-5">{report.review_items.map((item) => <li key={item.code}>{item.message} ({item.count})</li>)}</ul></div>}
      <div className="grid gap-3 md:grid-cols-4">{[["Прибыль", report.pnl.profit], ["Деньги на конец", report.cashflow.closing], ["Капитал", report.balance.equity], ["Расхождение баланса", report.balance.difference]].map(([label, value]) => <section key={label} className="rounded-xl border border-line bg-surface p-4"><h2 className="text-sm text-muted">{label}</h2><p className="mt-2 text-xl font-semibold tabular-nums">{value} BYN</p></section>)}</div>
      <div id="accounting-trial-balance" className="overflow-x-auto rounded-xl border border-line bg-surface"><table className="w-full text-sm"><caption className="p-3 text-left font-semibold">Оборотно-сальдовая ведомость</caption><thead><tr>{["Счёт / аналитика", "Валюта", "Начальное сальдо", "Дебет", "Кредит", "Конечное сальдо"].map((x) => <th key={x} className="border-b border-line p-3 text-left">{x}</th>)}</tr></thead><tbody>{report.trial_balance.map((row, i) => <tr key={i}><td className="border-b border-line p-3"><button className="text-accent underline" onClick={() => setAccountActivity(row)} aria-label={`Обороты ${row.account} ${Object.values(row.dimensions).join(" ")} ${row.currency}`}>{row.account} · {row.title}</button>{row.off_balance && " (забалансовый)"}<div className="text-xs text-muted">{Object.entries(row.dimensions).map(([k, v]) => `${labels[k] || k}: ${v}`).join(" · ")}</div></td><td className="p-3">{row.currency}</td>{[row.opening, row.debit, row.credit, row.closing].map((v, j) => <td key={j} className="p-3 text-right tabular-nums">{v}</td>)}</tr>)}</tbody></table>{!report.trial_balance.length && <p className="p-4 text-muted">За выбранный период нет проводок.</p>}</div>
      {accountActivity && <AccountingAccountActivity row={accountActivity} movements={report.movements} openingMovements={report.opening_movements} onEntry={(id) => void openEntry(id)} onClose={() => setAccountActivity(null)} />}
      <section id="accounting-journal" className="rounded-xl border border-line bg-surface p-4"><h2 className="mb-3 font-semibold">Проводки за период</h2>{report.movements.map((m, i) => <div key={i} className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-2 text-sm"><button className="text-accent underline" onClick={() => void openEntry(m.entry_id)}>№ {m.entry_id} · {m.source}</button><span>{m.date} · {m.side === "debit" ? "Дт" : "Кт"} {m.account}</span><span className="tabular-nums">{m.amount} BYN</span></div>)}</section>
    </>}
    {tab === "accounts" && <section className="rounded-xl border border-line bg-surface p-4"><h2 className="font-semibold">Рабочий план счетов</h2><p className="my-2 text-sm text-muted">Действует на {operationDate}. Настройки и версии утверждает главный бухгалтер.</p>{accounts.map((a) => <div key={a.id} className="border-b border-line py-3"><span className="font-semibold">{a.code}</span> · {a.title}<p className="text-xs text-muted">{a.required_dimensions.map((d) => labels[d] || d).join(" · ") || "Без обязательной аналитики"}</p></div>)}{!accounts.length && <p className="py-4 text-muted">Рабочий план счетов ещё не настроен.</p>}</section>}
    {tab === "entry" && <section className="space-y-4 rounded-xl border border-line bg-surface p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">Бухгалтерская справка {manualDocument?.number ?? "· новый документ"}</h2><Button variant="secondary" disabled={locked || manualCreateRecovery.status !== "none"} onClick={newManualDocument}>Новая справка</Button></div>
      <section aria-label="Список бухгалтерских справок" className="rounded-lg border border-line p-3"><h3 className="font-semibold">Реестр справок</h3>{manualDocuments?.items.map((row) => <button key={row.id} className="block py-1 text-left text-accent underline" onClick={() => void openManualDocument(row.id)} disabled={locked}>{row.number} · {row.source} · {row.posting_date} · {row.status === "posted" ? "проведена" : row.status === "voided" ? "аннулирована" : "черновик"}</button>)}{manualDocuments && !manualDocuments.items.length && <p className="text-sm text-muted">Справок пока нет.</p>}{manualDocuments?.next_before_id != null && <Button variant="secondary" disabled={locked} onClick={() => { const cursor = manualDocuments.next_before_id; void request<ManualDocumentList>(`/organizations/${org}/manual-documents?before_id=${cursor}`).then((next) => { if (String(next.organization_id) === org) setManualDocuments({ ...next, items: [...manualDocuments.items, ...next.items] }); }).catch((reason: Error) => setError(reason.message)); }}>Ещё справки</Button>}</section>
      {manualDocument && <p className="text-sm text-muted">{manualDocument.status === "posted" ? "Проведена" : manualDocument.status === "voided" ? "Аннулирована" : "Черновик"} · версия {manualDocument.version} · изменена {manualDocument.updated_at}{manualDocument.entry_id != null && <Button variant="ghost" onClick={() => void openEntry(manualDocument.entry_id!)}>Открыть проводку № {manualDocument.entry_id}</Button>}{manualDocument.status === "posted" && manualDocument.entry_id != null && <Button variant="secondary" disabled={locked} onClick={startManualCorrection}>Создать исправление</Button>}</p>}
      <fieldset disabled={locked || (!manualDocument && manualCreateRecovery.status !== "none") || (manualDocument != null && manualDocument.status !== "draft")} className="space-y-4"><div className="grid gap-3 md:grid-cols-3"><label>Основание<Input aria-label="Основание" value={source} disabled={locked} onChange={(e) => { invalidatePreview(); setSource(e.target.value); }} placeholder="Номер документа" /></label><label>Дата отражения<Input aria-label="Дата операции" type="date" value={operationDate} disabled={locked} onChange={(e) => changeDate("operation", e.target.value)} /></label><label>Содержание<Input aria-label="Содержание" value={explanation} disabled={locked} onChange={(e) => { invalidatePreview(); setExplanation(e.target.value); }} /></label></div>
      <div className="grid gap-3 md:grid-cols-4"><label className="text-sm">Дата документа<Input aria-label="Дата документа" type="date" value={documentDate} disabled={locked} onChange={(e) => { invalidatePreview(); setDocumentDate(e.target.value); }} /></label><label className="text-sm">Дата хозяйственной операции<Input aria-label="Дата хозяйственной операции" type="date" value={economicDate} disabled={locked} onChange={(e) => { invalidatePreview(); setEconomicDate(e.target.value); }} /></label><label className="text-sm">Версия документа<Input aria-label="Версия документа" type="number" min="1" step="1" value={sourceVersion} disabled={locked} onChange={(e) => { invalidatePreview(); setSourceVersion(Number(e.target.value)); }} /></label><label className="text-sm">Исправляет операцию №<Input aria-label="Исправляет операцию" type="number" min="1" step="1" value={correctionOf} disabled={locked} onChange={(e) => { invalidatePreview(); setCorrectionOf(e.target.value); }} placeholder="Если это исправление" /></label></div>
      {correctionOf && <p className="rounded-lg border border-amber-300 p-3 text-sm">Корректирующая справка добавляет проводки к исходной операции. Укажите только сумму и количество разницы; итоговые суммы исходного документа повторно не вводите.</p>}
      {lines.map((line, i) => <fieldset key={i} disabled={locked} className="space-y-2 rounded-lg border border-line p-3"><legend className="text-sm">Строка {i + 1}</legend><div className="grid gap-3 md:grid-cols-3"><Select aria-label={`Сторона ${i + 1}`} value={line.side} onChange={(e) => changeLine(i, { side: e.target.value as "debit" | "credit" })}><option value="debit">Дебет</option><option value="credit">Кредит</option></Select><Select aria-label={`Счёт ${i + 1}`} value={line.account} onChange={(e) => changeLine(i, { account: e.target.value, dimensions: {}, cash_activity: undefined, currency: "BYN", original_amount: undefined, rate: undefined, rate_scale: undefined, rate_date: undefined, rate_source: undefined, quantity: undefined })}><option value="">Выберите счёт</option>{accounts.map((a) => <option key={a.id} value={a.code}>{a.code} · {a.title}</option>)}</Select><Input aria-label={`Сумма ${i + 1}`} inputMode="decimal" value={line.amount} placeholder="0.00 BYN" onChange={(e) => changeLine(i, { amount: e.target.value })} /></div>{accounts.find((a) => a.code === line.account)?.required_dimensions.map((dimension) => dimension === "counterparty" ? <CounterpartyDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => { const next = Object.fromEntries(Object.entries(line.dimensions).filter(([key]) => !key.startsWith("counterparty") && !key.startsWith("contract") && !key.startsWith("settlement_document"))); changeLine(i, { dimensions: { ...next, ...snapshot } }); }} /> : dimension === "contract" ? <ContractDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => { const next = Object.fromEntries(Object.entries(line.dimensions).filter(([key]) => !key.startsWith("settlement_document"))); changeLine(i, { dimensions: { ...next, ...snapshot } }); }} /> : dimension === "settlement_document" ? <SettlementDocumentDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => changeLine(i, { dimensions: { ...line.dimensions, ...snapshot } })} />  : dimension === "asset" ? <FixedAssetDimensionPicker key={org + "/asset/" + i} org={org} index={i} dimensions={line.dimensions} assets={fixedAssets} assetsOrg={fixedAssetsOrg} loading={fixedAssetsLoading} error={fixedAssetsErrorForOrg} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => { const next = Object.fromEntries(Object.entries(line.dimensions).filter(([key]) => !fixedAssetDimensionKeys.has(key))); changeLine(i, { dimensions: { ...next, ...snapshot } }); }} /> : dimension === "sku" ? <SkuDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => changeLine(i, { dimensions: { ...line.dimensions, ...snapshot } })} /> : dimension === "warehouse" ? <WarehouseDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => changeLine(i, { dimensions: { ...line.dimensions, ...snapshot } })} /> : dimension === "order" ? <OrderDimensionPicker key={`${org}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} onSelect={(snapshot) => { const next = Object.fromEntries(Object.entries(line.dimensions).filter(([key]) => key !== "order" && !key.startsWith("order_"))); changeLine(i, { dimensions: { ...next, ...snapshot } }); }} /> : dimension === "employee" ? <EmployeeDimensionPicker key={`${org}/${economicDate}/${manualDocument?.id ?? "new"}/${manualDocument?.version ?? 0}/${i}/${line.account}/${dimension}`} org={org} onDate={economicDate} index={i} dimensions={line.dimensions} disabled={locked || (manualDocument != null && manualDocument.status !== "draft")} requiresDepartment={accounts.find((a) => a.code === line.account)?.required_dimensions.includes("department") ?? false} onSelect={(snapshot) => { const next = Object.fromEntries(Object.entries(line.dimensions).filter(([key]) => key !== "employee" && key !== "employment_binding_id" && key !== "department" && !key.startsWith("employee_"))); changeLine(i, { dimensions: { ...next, ...snapshot } }); }} /> : dimension === "department" && accounts.find((a) => a.code === line.account)?.required_dimensions.includes("employee") ? <label key={dimension} className="block text-sm">Подразделение строки {i + 1}<Input aria-label={`Подразделение строки ${i + 1}`} value={line.dimensions.department || ""} readOnly /><span className="text-xs text-muted">Заполняется из действующей привязки сотрудника.</span></label> : <label key={dimension} className="block text-sm">{labels[dimension] || dimension}<Input value={line.dimensions[dimension] || ""} onChange={(e) => changeLine(i, { dimensions: { ...line.dimensions, [dimension]: e.target.value } })} /></label>)}{accounts.find((a) => a.code === line.account)?.cash && <label className="block text-sm">Вид денежного потока<Select value={line.cash_activity || ""} onChange={(e) => changeLine(i, { cash_activity: e.target.value })}><option value="">Выберите вид</option><option value="operating">Текущая деятельность</option><option value="investing">Инвестиционная</option><option value="financing">Финансовая</option><option value="internal">Внутреннее перемещение</option></Select></label>}<AccountingCurrencyFields value={line} currency={accounts.find((a) => a.code === line.account)?.currency_tracking ?? false} quantity={accounts.find((a) => a.code === line.account)?.quantity_tracking ?? false} onChange={(patch) => changeLine(i, patch)} /></fieldset>)}
      <div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={locked} onClick={() => { invalidatePreview(); setLines([...lines, { account: "", side: "debit", amount: "", dimensions: {} }]); }}>Добавить строку</Button><Button disabled={locked || !org || !source || !explanation} onClick={() => void prepare()}>Проверить проводки</Button></div>
      {preview && <div className="rounded-xl border border-accent p-4"><h3 className="font-semibold">Проверенные проводки</h3><p className="my-2">{preview.explanation}</p>{preview.lines.map((line, i) => <p key={i}>{line.side === "debit" ? "Дт" : "Кт"} {line.account} · {line.title} — {line.amount} BYN</p>)}{!preview.normative_verified && <p className="my-2 text-sm text-muted">Нормативная база не подтверждена: закрытие периода будет недоступно.</p>}<div className="mt-3 flex flex-wrap gap-2"><Button disabled={locked || (!manualDocument && manualCreateRecovery.status !== "none")} onClick={() => void saveManual()}>Сохранить</Button><Button variant="secondary" disabled={locked || (!manualDocument && manualCreateRecovery.status !== "none")} onClick={() => void saveManual(true)}>Сохранить и закрыть</Button><Button disabled={locked || !manualDocument || manualDirty || manualDocument.revisions[manualDocument.revisions.length - 1]?.digest !== preview.digest} onClick={() => void post()}>Подтвердить и провести</Button><Button variant="secondary" disabled={locked || !manualDocument || manualDirty || manualDocument.revisions[manualDocument.revisions.length - 1]?.digest !== preview.digest} onClick={() => void post(true)}>Провести и закрыть</Button></div></div>}
      </fieldset>
      {manualDocument?.status === "draft" && <div className="flex flex-wrap items-end gap-3 rounded-lg border border-line p-3"><label className="min-w-64 flex-1 text-sm">Причина аннулирования<Input aria-label="Причина аннулирования справки" value={voidReason} disabled={locked} onChange={(event) => { setVoidReason(event.target.value); voidCommand.current = null; }} placeholder="Ошибочный черновик, дубликат…" /></label><Button variant="secondary" disabled={locked || manualDirty || !voidReason.trim()} onClick={() => void voidManualDocument()}>Аннулировать черновик</Button><p className="w-full text-xs text-muted">Проведённую справку аннулировать нельзя; для неё оформляют исправление. История черновика и причина аннулирования сохраняются.</p></div>}
      {manualDocument?.void && <p className="rounded-lg border border-line p-3 text-sm">Аннулирована: {manualDocument.void.reason} · {manualDocument.void.actor} · {manualDocument.void.created_at}</p>}
      {!!manualDocument?.revisions.length && <section aria-label="История справки" className="space-y-3 rounded-lg border border-line p-3"><h3 className="font-semibold">История изменений</h3>{manualDocument.revisions.map((revision, index) => <div key={revision.version} className="border-t border-line pt-2 text-sm"><p className="font-medium">Версия {revision.version} · {revision.actor} · {revision.created_at}</p>{describeRevision(manualDocument.revisions[index - 1]?.posting, revision.posting).map((change, changeIndex) => <p key={changeIndex}>{change}</p>)}</div>)}</section>}
    </section>}
    {detail && <section aria-label="Карточка проводки" className="min-w-0 break-words rounded-xl border border-accent bg-surface p-4">
      <div className="flex flex-wrap justify-between gap-2"><h2 className="font-semibold">Операция № {detail.id}</h2><Button variant="ghost" onClick={() => { entryGeneration.current += 1; setDetail(null); }}>Закрыть карточку</Button></div>
      <p>{detail.source}</p>
      {salesOriginal(org, detail.source)}
      <AccountingSourceLink org={org} source={detail.source} />
      {detail.source.startsWith(`wms:physical-shipment:${org}:`) && <AccountingShipmentPackage key={`${org}/${detail.id}`} org={org} entryId={detail.id} onEntry={(id) => void openEntry(id)} />}
      <dl className="my-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">{[
        ["Дата документа", detail.document_date], ["Дата хозяйственной операции", detail.operation_date],
        ["Дата отражения", detail.posting_date], ["Время регистрации (как сохранено)", detail.created_at],
        ["Кем проведено", detail.actor],
        ["Версия документа", detail.source_version], ["Версия правила", detail.rule_version],
      ].map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd>{value ?? "Не получено"}</dd></div>)}</dl>
      {detail.correction_of != null && <button className="text-accent underline" onClick={() => void openEntry(detail.correction_of!)}>Исправляет операцию № {detail.correction_of}</button>}
      {!!detail.corrections?.length && <section aria-label="История исправлений" className="my-3 space-y-2 rounded border border-line p-3"><h3 className="font-semibold">Позднейшие исправления</h3>{detail.corrections.map((item) => <button key={item.id} className="block text-left text-accent underline" onClick={() => void openEntry(item.id)}>Операция № {item.id} · версия {item.source_version} · {item.posting_date} · {item.actor} · {item.created_at}</button>)}</section>}
      {detail.changes && <section aria-label="Изменения бухгалтерской справки" className="my-3 space-y-2 rounded border border-line p-3"><h3 className="font-semibold">Отличия от предыдущей версии</h3><p className="text-sm text-muted">Старая запись сохранена; исправление добавлено отдельной операцией и влияет на итог как разница.</p>{detail.changes.fields.map((item) => <p key={item.field} className="text-sm">{({ source_version: "Версия документа", document_date: "Дата документа", operation_date: "Дата хозяйственной операции", posting_date: "Дата отражения", policy_id: "Учётная политика", explanation: "Содержание" } as Record<string, string>)[item.field] ?? item.field}: было «{item.before}», в исправлении «{item.after}».</p>)}{detail.changes.posting_changed && <details><summary>Исходная и корректирующая проводки</summary><div className="grid gap-3 md:grid-cols-2"><div><h4 className="font-semibold">Исходная операция</h4>{detail.changes.before_lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account_code} · {line.amount} {line.currency ?? "BYN"} · {JSON.stringify(line.dimensions)}</p>)}</div><div><h4 className="font-semibold">Корректирующая операция (разница)</h4>{detail.changes.after_lines.map((line, index) => <p key={index}>{line.side === "debit" ? "Дт" : "Кт"} {line.account_code} · {line.amount} {line.currency ?? "BYN"} · {JSON.stringify(line.dimensions)}</p>)}</div></div></details>}</section>}
      <p className="my-2 text-muted">{detail.explanation}</p>
      {detail.lines.map((line) => <div key={line.id} className="border-t border-line py-3">
        <p>{line.side === "debit" ? "Дт" : "Кт"} {line.account_code} · {line.account_title} — {line.amount} BYN</p>
        <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(line.dimensions ?? {}).map(([key, value]) => <div key={key}><dt className="text-muted">{key === "bank_statement" ? "Банковская выписка" : labels[key] || key}</dt><dd>{key === "settlement_document" ? salesOriginal(org, value) ?? value : value}</dd></div>)}</dl>
        {line.quantity != null && <p className="text-sm">Количество: {line.quantity}</p>}
        {line.currency && line.currency !== "BYN" && <div className="mt-2 text-sm">
          <p>Сумма в валюте: {line.original_amount ?? "Не получено"} {line.currency}</p>
          <p>Курс: {line.rate ?? "Не получено"} BYN за {line.rate_scale ?? "Не получено"} {line.currency}</p>
          <p>Дата курса: {line.rate_date ?? "Не получено"} · Источник: {line.rate_source ?? "Не получено"}</p>
        </div>}
      </div>)}
    </section>}
  </div>;
}
