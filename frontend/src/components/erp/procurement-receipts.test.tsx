import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createHash } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";

import { ProcurementReceiptDrafts } from "./procurement-receipt-drafts";
import { ProcurementReceipts } from "./procurement-receipts";

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

async function selectReceiptSku() {
  fireEvent.change(screen.getByLabelText("Поиск номенклатуры накладной"), { target: { value: "AKB" } });
  await screen.findByRole("option", { name: "AKB · Аккумулятор · шт · ID 31" });
  fireEvent.change(screen.getByLabelText("Номенклатура строки 1"), { target: { value: "31" } });
}

async function selectReceiptWarehouse() {
  fireEvent.change(screen.getByLabelText("Поиск склада накладной"), { target: { value: "Склад приемки" } });
  await screen.findByRole("option", { name: "receiving · Склад приемки · ID 9" });
  fireEvent.change(screen.getByLabelText("Склад накладной из справочника"), { target: { value: "9" } });
}

function explainUnregisteredContract() {
  fireEvent.change(screen.getByLabelText("Основание покупки без зарегистрированного договора"),
    { target: { value: "Поставка по счёту без зарегистрированного договора" } });
}

function emptyContracts(url: string) {
  return { organization_id: 7, supplier_id: 19,
    status: url.includes("status=revoked") ? "revoked" : "active", items: [], truncated: false };
}

function emptyWarehouses(url: string) {
  return { organization_id: Number(url.match(/\/organizations\/(\d+)\//)?.[1]),
    items: [], truncated: false };
}

function durableReceiptDocument(invoiceReference = "INV-DURABLE") {
  return {
    currency: "BYN", invoice_reference: invoiceReference, document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19,
    supplier_unp: "190000001", contract: "Без договора", contract_basis: "Поставка без договора",
    warehouse: "receiving", warehouse_id: 9, warehouse_title: "Склад приемки",
    explanation: "Товар", items: [{ order_id: null, sku_id: 31,
      sku_title: "Аккумулятор", sku: "AKB", unit: "шт", lot: "LOT-1", quantity: "2.000001",
      net_amount: "100.01", vat_rate: "20", vat_amount: "20.00", vat_basis: "ОСН" }],
  };
}

function correctionReadiness(receiptId = 92, flagOverrides: Record<string, boolean> = {}, overrides: Record<string, unknown> = {}) {
  const flags = { physical_change: false, inventory_value_change: false, vat_change: false,
    primary_document_change: false, operation_date_change: false, explanation_only: false, no_difference: true,
    ...flagOverrides };
  return { organization_id: 7, receipt_id: receiptId, current_version: 1,
    correction_of: { receipt_id: 81, version: 3, entry_id: 42 },
    classification: Object.entries(flags).filter(([, changed]) => changed).map(([flag]) => flag), ...flags,
    posting_available: false, wms_movement_available: false,
    blockers: flags.no_difference || flags.explanation_only ? ["no_economic_difference", "posting_workflow_not_approved"] : ["posting_workflow_not_approved"],
    ...overrides };
}

function correctionRow(id = 92, invoiceReference = `CORR-${id}`, version = 1) {
  const document = { currency: "BYN", invoice_reference: invoiceReference, document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19, supplier_unp: "190000001",
    contract: "D-1", contract_id: 50, contract_basis: null, warehouse: "Основной", explanation: "Исправление", items: [] };
  return { id, organization_id: 7, version, status: "draft", posting: null,
    correction_of: { receipt_id: 81, version: 3, entry_id: 42 },
    revisions: [{ version, actor: "accountant", created_at: "2026-09-26", document }] };
}

function correctionRowWithHistory(id = 92, version = 2) {
  const row = correctionRow(id, `CORR-${id}`, version);
  const prior = { ...row.revisions[0], version: version - 1, actor: "accountant",
    created_at: "2026-09-25", document: { ...row.revisions[0].document, invoice_reference: `CORR-${id}-V${version - 1}` } };
  return { ...row, revisions: [prior, ...row.revisions] };
}

function vatOnlyCorrectionReadiness(receiptId = 92, receiptVersion = 1) {
  return correctionReadiness(receiptId, { vat_change: true, no_difference: false }, {
    current_version: receiptVersion,
    blockers: ["vat_register_and_eschf_evidence_required", "correction_posting_period_required", "posting_workflow_not_approved"],
  });
}

function inboundEvidenceFile(kind: "supplier_eschf_xml" | "supporting_document_pdf" = "supplier_eschf_xml",
  overrides: Record<string, unknown> = {}) {
  const pdf = kind === "supporting_document_pdf";
  return {
    file_id: 12, organization_id: 7, receipt_id: 92, receipt_version: 1, kind,
    tax_period: "2026-09", reference: pdf ? "PDF-1" : "ЭСЧФ-1",
    filename: pdf ? "support.pdf" : "invoice.xml", content_type: pdf ? "application/pdf" : "application/xml",
    size_bytes: 9, sha256: "a".repeat(64), evidence: "Получено от поставщика",
    request_key: "11111111-1111-4111-8111-111111111111", supersedes_id: null,
    digest: "b".repeat(64), actor: "accountant@example.test", created_at: "2026-09-27T10:00:00Z",
    is_current: true, bytes_verified_at_upload: true, signature_verified: false,
    document_facts_verified: false, posting_available: false, ...overrides,
  };
}

function correctionEvidenceFetcher(options: {
  readiness?: unknown;
  rows?: ReturnType<typeof correctionRow>[];
  xml?: unknown;
  pdf?: unknown;
  onPost?: (body: Record<string, unknown>) => unknown;
} = {}) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/receipt-correction-evidence-files") && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      const response = options.onPost?.(body) ?? inboundEvidenceFile(
        body.kind as "supplier_eschf_xml" | "supporting_document_pdf",
        { file_id: 14, request_key: body.request_key, receipt_id: body.receipt_id,
          receipt_version: body.receipt_version, tax_period: body.tax_period, reference: body.reference,
          filename: body.filename, content_type: body.kind === "supporting_document_pdf" ? "application/pdf" : "application/xml",
          size_bytes: Number(String(body.data_url).split(",")[1] ? Buffer.from(String(body.data_url).split(",")[1], "base64").length : 0),
          sha256: createHash("sha256").update(Buffer.from(String(body.data_url).split(",")[1] ?? "", "base64")).digest("hex"),
          evidence: body.evidence, supersedes_id: body.supersedes_id, is_current: true });
      return { ok: true, json: async () => response };
    }
    if (url.includes("/receipt-correction-evidence-files")) {
      const kind = url.includes("kind=supporting_document_pdf") ? "supporting_document_pdf" : "supplier_eschf_xml";
      return { ok: true, json: async () => kind === "supplier_eschf_xml" ? options.xml ?? [] : options.pdf ?? [] };
    }
    if (url.includes("correction-readiness")) return { ok: true, json: async () => options.readiness ?? vatOnlyCorrectionReadiness() };
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("receipt-documents")) return { ok: true, json: async () => options.rows ?? [correctionRow()] };
    return { ok: true, json: async () => [] };
  });
}

function canonicalWorkpaper(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalWorkpaper).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalWorkpaper((value as Record<string, unknown>)[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

function workpaperDigest(value: unknown) {
  return createHash("sha256").update(canonicalWorkpaper(value)).digest("hex");
}

function workpaperEvidence(receiptId = 92, receiptVersion = 2, taxPeriod = "2026-09") {
  const xml = inboundEvidenceFile("supplier_eschf_xml", { file_id: 13, receipt_id: receiptId,
    receipt_version: receiptVersion, tax_period: taxPeriod, filename: "invoice-v2.xml", sha256: "a".repeat(64), digest: "b".repeat(64) });
  const pdf = inboundEvidenceFile("supporting_document_pdf", { file_id: 21, receipt_id: receiptId,
    receipt_version: receiptVersion, tax_period: taxPeriod, filename: "proof-v2.pdf", sha256: "c".repeat(64), digest: "d".repeat(64) });
  return { xml, pdf };
}

function workpaperSnapshot(receiptId = 92, receiptVersion = 2, taxPeriod = "2026-09",
  options: { lineId?: number; xmlTaxPeriod?: string; organizationId?: number; extraLineFields?: Record<string, unknown> } = {}) {
  const evidence = workpaperEvidence(receiptId, receiptVersion, taxPeriod);
  const evidenceSnapshot = [
    { file_id: evidence.xml.file_id, receipt_id: receiptId, receipt_version: receiptVersion, kind: "supplier_eschf_xml",
      tax_period: taxPeriod, reference: evidence.xml.reference, filename: evidence.xml.filename,
      content_type: evidence.xml.content_type, size_bytes: evidence.xml.size_bytes, sha256: evidence.xml.sha256, digest: evidence.xml.digest },
    { file_id: evidence.pdf.file_id, receipt_id: receiptId, receipt_version: receiptVersion, kind: "supporting_document_pdf",
      tax_period: options.xmlTaxPeriod ?? taxPeriod, reference: evidence.pdf.reference, filename: evidence.pdf.filename,
      content_type: evidence.pdf.content_type, size_bytes: evidence.pdf.size_bytes, sha256: evidence.pdf.sha256, digest: evidence.pdf.digest },
  ];
  const flags = { review_only: true, signature_verified: false, document_facts_verified: false,
    deduction_eligibility_assessed: false, accountant_accepted: false, posting_available: false };
  return {
    organization_id: options.organizationId ?? 7,
    receipt: { correction_receipt_id: receiptId, correction_version: receiptVersion,
      correction_revision_id: receiptId * 10 + receiptVersion, correction_document_digest: "e".repeat(64),
      original_receipt_id: 81, original_version: 3, original_revision_id: 813,
      original_document_digest: "f".repeat(64), source_entry_id: 42, source_entry: "procurement:receipt:81",
      source_version: 3, source_entry_digest: "1".repeat(64), source_posting_date: "2026-09-24", source_operation_date: "2026-09-24" },
    tax_period: taxPeriod, classification: ["vat_change"],
    source_account_18_lines: [{ line_id: options.lineId ?? 501, account_id: 18, account_code: "18.01",
      account_title: "НДС по приобретённым ценностям", category: "vat", cash: false, amount: "20.00",
      currency: "BYN", dimensions: {}, ...options.extraLineFields }],
    evidence_files: evidenceSnapshot, ...flags,
  };
}

function workpaperPreviewValue(receiptId = 92, receiptVersion = 2, taxPeriod = "2026-09",
  options: Parameters<typeof workpaperSnapshot>[3] = {}) {
  const basis = workpaperSnapshot(receiptId, receiptVersion, taxPeriod, options);
  return { organization_id: 7, receipt_id: receiptId, receipt_version: receiptVersion,
    original_receipt_id: 81, original_version: 3, tax_period: taxPeriod, basis,
    basis_digest: workpaperDigest(basis), status: "review_only_workpaper_ready",
    source_account_18_line_count: basis.source_account_18_lines.length,
    current_evidence_file_count: basis.evidence_files.length, evidence_bytes_verified_at_review: true,
    review_only: true, signature_verified: false, document_facts_verified: false,
    deduction_eligibility_assessed: false, accountant_accepted: false, posting_available: false };
}

function savedWorkpaper(body: Record<string, unknown>, options: { id?: number; revision?: number; organizationId?: number; flags?: Record<string, unknown> } = {}) {
  const receiptId = Number(body.receipt_id), receiptVersion = Number(body.receipt_version), taxPeriod = String(body.tax_period);
  const snapshot = workpaperSnapshot(receiptId, receiptVersion, taxPeriod);
  const bodyTyped = body as { request_key: string; receipt_id: number; receipt_version: number; tax_period: string;
    basis_digest: string; reviewer_evidence: string; supersedes_workpaper_id: number | null };
  const flags = { review_only: true, signature_verified: false, document_facts_verified: false,
    deduction_eligibility_assessed: false, accountant_accepted: false, posting_available: false, ...options.flags };
  return { workpaper_id: options.id ?? 501, organization_id: options.organizationId ?? 7,
    receipt_id: receiptId, receipt_version: receiptVersion, original_receipt_id: 81, original_version: 3,
    source_entry_id: 42, source_entry_digest: "1".repeat(64), tax_period: taxPeriod,
    revision: options.revision ?? 1, supersedes_workpaper_id: bodyTyped.supersedes_workpaper_id,
    request_key: bodyTyped.request_key, request_digest: workpaperDigest(bodyTyped), basis_digest: bodyTyped.basis_digest,
    snapshot_digest: workpaperDigest(snapshot), reviewer_evidence: bodyTyped.reviewer_evidence,
    reviewed_by: "accountant@example.test", created_at: "2026-09-27T10:00:00Z", snapshot,
    status: "review_only_workpaper", evidence_bytes_verified_at_review: true, ...flags };
}

function pendingWorkpaperJournal(receiptVersion = 1, taxPeriod = "2026-09", requestKey = "95bd12f3-a45c-4b89-b005-2f9fa22c38a1") {
  const body = { request_key: requestKey, receipt_id: 92,
    receipt_version: receiptVersion, tax_period: taxPeriod, basis_digest: workpaperDigest(workpaperSnapshot(92, receiptVersion, taxPeriod)),
    reviewer_evidence: "Проверена связь документа с источником.", supersedes_workpaper_id: null };
  return { key: `inbound-vat-correction-workpaper:v1:7:92:${receiptVersion}:${taxPeriod}`, body,
    bodyJson: JSON.stringify(body), journalJson: JSON.stringify({ organization_id: 7, receipt_id: 92,
      receipt_version: receiptVersion, tax_period: taxPeriod, request_key: body.request_key,
      body_json: JSON.stringify(body) }) };
}

function inboundVatWorkpaperFetcher(options: {
  rows?: ReturnType<typeof correctionRow>[];
  evidence?: Record<number, { xml: ReturnType<typeof inboundEvidenceFile>; pdf: ReturnType<typeof inboundEvidenceFile> }>;
  preview?: (body: Record<string, unknown>) => unknown | Promise<unknown>;
  onConfirm?: (body: Record<string, unknown>, rawBody: string) => unknown | Promise<unknown>;
  onByRequest?: (key: string) => unknown | Promise<unknown>;
}) {
  const saved = new Map<string, unknown>();
  const confirmedBodies: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("receipt-warehouse-options")) {
      const organizationId = Number(url.match(/\/organizations\/(\d+)\//)?.[1] ?? 7);
      return { ok: true, json: async () => ({ organization_id: organizationId,
        items: [{ id: 9, name: "receiving", title: "Склад приемки", is_active: true }], truncated: false }) };
    }
    if (url.includes("/inbound-vat-correction-workpapers/preview")) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return { ok: true, json: async () => options.preview ? options.preview(body)
        : workpaperPreviewValue(Number(body.receipt_id), Number(body.receipt_version), String(body.tax_period)) };
    }
    if (url.endsWith("/inbound-vat-correction-workpapers") && init?.method === "POST") {
      const rawBody = String(init.body), body = JSON.parse(rawBody) as Record<string, unknown>;
      confirmedBodies.push(rawBody);
      const result = options.onConfirm ? await options.onConfirm(body, rawBody) : savedWorkpaper(body);
      saved.set(String(body.request_key), result);
      return { ok: true, status: 201, json: async () => result };
    }
    if (url.includes("/inbound-vat-correction-workpapers/by-request/")) {
      const key = url.split("/by-request/")[1];
      const result = options.onByRequest ? await options.onByRequest(key) : saved.get(key);
      return result ? { ok: true, status: 200, json: async () => result }
        : { ok: false, status: 404, json: async () => ({ detail: "not found" }) };
    }
    if (url.includes("/inbound-vat-correction-workpapers?")) {
      const query = new URL(url, "http://localhost").searchParams;
      const items = [...saved.values()].filter((value) => {
        const row = value as Record<string, unknown>;
        return row.receipt_id === Number(query.get("receipt_id"))
          && row.receipt_version === Number(query.get("receipt_version")) && row.tax_period === query.get("tax_period");
      });
      return { ok: true, json: async () => items };
    }
    if (url.includes("/receipt-correction-evidence-files")) {
      const query = new URL(url, "http://localhost").searchParams;
      const id = Number(query.get("receipt_id")), data = options.evidence?.[id] ?? workpaperEvidence(id, 2);
      return { ok: true, json: async () => query.get("kind") === "supplier_eschf_xml" ? [data.xml] : [data.pdf] };
    }
    if (url.includes("correction-readiness")) {
      const id = Number(url.match(/receipt-documents\/(\d+)/)?.[1] ?? 92);
      return { ok: true, json: async () => vatOnlyCorrectionReadiness(id, 2) };
    }
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("receipt-documents")) return { ok: true, json: async () => options.rows ?? [correctionRow(92, "CORR-92", 2)] };
    return { ok: true, json: async () => [] };
  });
  return { fetcher, saved, confirmedBodies };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

it("requires an explicit legal entity before opening supplier invoices", async () => {
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => [
    { id: 7, name: "Белакб", unp: "123456789" },
  ] }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceipts />);
  expect(await screen.findByRole("option", { name: /Белакб/ })).toBeInTheDocument();
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("");
  expect(screen.getByText("Выберите юрлицо перед просмотром или созданием накладной.")).toBeInTheDocument();
  expect(screen.queryByText("Новая первичная накладная")).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("shows draft and posted invoices from every date in the procurement register", async () => {
  const document = (invoice_reference: string, supplier: string, document_date: string) => ({
    currency: "BYN", invoice_reference, document_date, operation_date: document_date,
    supplier, contract: "Contract", warehouse: "Warehouse", explanation: "Goods", items: [],
  });
  const rows = [
    { id: 2, version: 1, status: "posted", posting: { entry_id: 42, version: 1 },
      revisions: [{ version: 1, actor: "accountant", created_at: "2026-08-01", document: document("INV-OLD", "Acme", "2026-08-01") }] },
    { id: 3, version: 1, status: "draft", posting: null,
      revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: document("INV-NEW", "Beta", "2026-09-24") }] },
  ];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" date="2026-09-24" />);
  expect(await screen.findByText("Показано 2 из 2 накладных выбранного юрлица за все даты.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /INV-OLD/ })).toHaveTextContent("2026-08-01 · Acme");
  expect(screen.getByText("Проведена · версия 1")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть проведённую накладную" })).toHaveAttribute(
    "href", "/erp/procurement/receipts/posted/42?org=7",
  );
  expect(screen.getByText("Черновик · версия 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /INV-NEW/ }));
  expect(screen.queryByText("Проверка исправления")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("correction-readiness"))).toBe(false);

  fireEvent.change(screen.getByLabelText("Поиск накладных"), { target: { value: "Acme" } });
  expect(screen.getByText("Показано 1 из 2 накладных выбранного юрлица за все даты.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /INV-NEW/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Статус накладной"), { target: { value: "draft" } });
  expect(screen.getByText("Накладных по выбранному фильтру нет.")).toBeInTheDocument();
});

it("identifies linked correction drafts and keeps accounting and WMS actions hidden", async () => {
  const rows = [correctionRow(92, "CORR-1")];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("correction-readiness")
    ? correctionReadiness() : url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" date="2026-09-26" />);
  expect(await screen.findByText("Черновик исправления · версия 1")).toBeInTheDocument();
  expect(screen.getByText(/К накладной № 81, версия 3 · проводка № 42/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-1/ }));
  expect(screen.getByText(/Связанный черновик исправления/).textContent).toContain("Исходная накладная и её проводка не меняются");
  expect(screen.getByText(/Связанный черновик исправления/).textContent).toContain("передача в WMS заблокированы до отдельного workflow");
  expect(await screen.findByText("Проверка исправления")).toBeInTheDocument();
  expect(screen.getByText("Проведение недоступно. Эта проверка показывает различия и не выдаёт разрешение; движение WMS также недоступно.")).toBeInTheDocument();
  expect(fetcher.mock.calls.find(([url]) => url.includes("correction-readiness"))?.[1]).toMatchObject({ cache: "no-store" });
  expect(screen.queryByRole("link", { name: "Подготовить складскую приёмку" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it("explains each correction classification flag without enabling posting", async () => {
  const flags = { physical_change: true, inventory_value_change: true, vat_change: true,
    primary_document_change: true, operation_date_change: true, no_difference: false };
  const rows = [correctionRow(92), correctionRow(93), correctionRow(94)];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/92/correction-readiness")
    ? correctionReadiness(92, flags, { blockers: ["physical_receipt_adjustment_required", "inventory_cost_layer_correction_required",
      "vat_register_and_eschf_evidence_required", "primary_document_reissue_evidence_required", "correction_posting_period_required",
      "posting_workflow_not_approved"] }) : url.includes("/93/correction-readiness")
      ? correctionReadiness(93, { no_difference: false, explanation_only: true }) : url.includes("/94/correction-readiness")
        ? correctionReadiness(94) : url.includes("supplier-contracts") ? emptyContracts(url)
          : url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Изменилось количество или склад/)).toBeInTheDocument();
  expect(screen.getByText(/может повлиять на слой себестоимости/)).toBeInTheDocument();
  expect(screen.getByText(/^Изменилась ставка, сумма или основание НДС/)).toBeInTheDocument();
  expect(screen.getByText(/^Изменились реквизиты первичного документа/)).toBeInTheDocument();
  expect(screen.getByText(/Дата операции изменилась/)).toBeInTheDocument();
  expect(screen.getByText("Процесс проведения исправлений пока не утверждён.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(await screen.findByText(/Изменилось только пояснение/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-94/ }));
  expect(await screen.findByText("Различий между исходной накладной и исправлением не выявлено.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it("fails closed for foreign and malformed readiness responses", async () => {
  const rows = [correctionRow(92), correctionRow(93), correctionRow(94)];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/92/correction-readiness")
    ? correctionReadiness(92, {}, { organization_id: 8 }) : url.includes("/93/correction-readiness")
      ? correctionReadiness(93, {}, { blockers: ["__proto__"] }) : url.includes("/94/correction-readiness")
        ? correctionReadiness(94, { no_difference: false }, { blockers: ["posting_workflow_not_approved"] })
        : url.includes("receipt-warehouse-options") ? emptyWarehouses(url)
          : url.includes("supplier-contracts") ? emptyContracts(url) : url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Не удалось подтвердить проверку для выбранного юрлица и версии/))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByText(/Изменение количества или склада не выявлено/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(await within(screen.getByRole("region", { name: "Проверка исправления" })).findByRole("alert"))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByText(/Различий между исходной накладной и исправлением не выявлено/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-94/ }));
  expect(await within(screen.getByRole("region", { name: "Проверка исправления" })).findByRole("alert"))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it("ignores readiness responses made stale by changing the selected correction or organization", async () => {
  const oldDocumentResponse = deferred<unknown>(), oldOrganizationResponse = deferred<unknown>();
  const rows = [correctionRow(92), correctionRow(93)];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/92/correction-readiness")
    ? oldDocumentResponse.promise : url.includes("/93/correction-readiness") ? oldOrganizationResponse.promise
      : url.includes("receipt-warehouse-options") ? emptyWarehouses(url)
        : url.includes("supplier-contracts") ? emptyContracts(url)
        : url.includes("purchase-ownership") ? [] : url.includes("/organizations/7/") ? rows : [] }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes("/92/correction-readiness"))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes("/93/correction-readiness"))).toBe(true));
  await act(async () => {
    oldDocumentResponse.resolve(correctionReadiness(92, { physical_change: true, no_difference: false }));
    await oldDocumentResponse.promise;
  });
  expect(screen.getByText("Загрузка проверки для текущей версии исправления…")).toBeInTheDocument();
  view.rerender(<ProcurementReceiptDrafts org="8" />);
  expect(await within(screen.getByRole("region", { name: "Проверка исправления" })).findByRole("alert"))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  await act(async () => {
    oldOrganizationResponse.resolve(correctionReadiness(93, { vat_change: true, no_difference: false }));
    await oldOrganizationResponse.promise;
  });
  expect(screen.getByText(/Не удалось подтвердить проверку для выбранного юрлица и версии/))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(fetcher.mock.calls.some(([url]) => url.includes("/organizations/8/receipt-documents/93/correction-readiness"))).toBe(false);
  expect(screen.queryByText(/Изменилось количество или склад/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Изменилась ставка/)).not.toBeInTheDocument();
});

it("shows current and historical evidence for both kinds after exact VAT-only readiness", async () => {
  const oldXml = inboundEvidenceFile("supplier_eschf_xml", {
    file_id: 12, filename: "invoice-old.xml", reference: "ЭСЧФ-старый", is_current: false,
  });
  const currentXml = inboundEvidenceFile("supplier_eschf_xml", {
    file_id: 13, filename: "invoice-current.xml", reference: "ЭСЧФ-новый", supersedes_id: 12,
  });
  const currentPdf = inboundEvidenceFile("supporting_document_pdf", { file_id: 21, filename: "proof.pdf", reference: "Акт-21" });
  const fetcher = correctionEvidenceFetcher({ xml: [oldXml, currentXml], pdf: [currentPdf] });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));

  expect(await screen.findByText(/invoice-old\.xml/)).toBeInTheDocument();
  expect(screen.getByText(/invoice-current\.xml/)).toBeInTheDocument();
  expect(screen.getByText(/proof\.pdf/)).toBeInTheDocument();
  expect(screen.getByText(/ЭСЧФ-старый/)).toBeInTheDocument();
  expect(screen.getAllByText(/accountant@example\.test/)).toHaveLength(3);
  expect(screen.getAllByText(new RegExp("a".repeat(64)))).toHaveLength(3);
  const evidenceCalls = fetcher.mock.calls.filter(([url]) => url.includes("/receipt-correction-evidence-files"));
  expect(evidenceCalls.map(([url]) => url)).toEqual(expect.arrayContaining([
    "/api/accounting/organizations/7/receipt-correction-evidence-files?receipt_id=92&receipt_version=1&kind=supplier_eschf_xml",
    "/api/accounting/organizations/7/receipt-correction-evidence-files?receipt_id=92&receipt_version=1&kind=supporting_document_pdf",
  ]));
  expect(screen.getByText(/Файл сам по себе не подтверждает подлинность подписи или факты документа/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it.each([
  ["foreign organization", { organization_id: 8 }],
  ["different receipt revision", { receipt_version: 2 }],
])("fails closed when evidence metadata names a %s", async (_label, overrides) => {
  const fetcher = correctionEvidenceFetcher({ xml: [inboundEvidenceFile("supplier_eschf_xml", overrides)] });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));

  expect(await screen.findByText("Не удалось проверить принадлежность и целостность документов. Просмотр и загрузка доказательств заблокированы.")).toBeInTheDocument();
  expect(screen.queryByText(/invoice\.xml/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Открыть файл/ })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("/receipt-correction-evidence-files") && init?.method === "POST")).toBe(false);
});

it("hides upload controls when VAT readiness includes a physical change or enables posting", async () => {
  const combined = correctionReadiness(92, { physical_change: true, vat_change: true, no_difference: false }, {
    blockers: ["physical_receipt_adjustment_required", "vat_register_and_eschf_evidence_required",
      "correction_posting_period_required", "posting_workflow_not_approved"],
  });
  const fetcher = correctionEvidenceFetcher({ readiness: combined });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findAllByText(/Загрузка недоступна: требуется точное VAT-only изменение/)).toHaveLength(2);
  expect(screen.queryByLabelText("Файл доказательства: supplier_eschf_xml")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it("sends the current file id as supersedes_id and checks uploaded bytes and receipt metadata", async () => {
  const current = inboundEvidenceFile("supplier_eschf_xml", { file_id: 12 });
  let posted: Record<string, unknown> | null = null;
  const fetcher = correctionEvidenceFetcher({
    xml: [current],
    onPost: (body) => {
      posted = body;
      const raw = Buffer.from(String(body.data_url).split(",")[1], "base64");
      return inboundEvidenceFile("supplier_eschf_xml", {
        file_id: 13, receipt_id: body.receipt_id, receipt_version: body.receipt_version,
        request_key: body.request_key, tax_period: body.tax_period, reference: body.reference,
        filename: body.filename, size_bytes: raw.length, sha256: createHash("sha256").update(raw).digest("hex"),
        evidence: body.evidence, supersedes_id: body.supersedes_id,
      });
    },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText(/invoice\.xml/);
  fireEvent.change(screen.getByLabelText("Основание документа: supplier_eschf_xml"), { target: { value: "ЭСЧФ-2026-09" } });
  fireEvent.change(screen.getByLabelText("Налоговый период: supplier_eschf_xml"), { target: { value: "2026-09" } });
  fireEvent.change(screen.getByLabelText("Комментарий к загрузке: supplier_eschf_xml"), { target: { value: "Исправленный счёт-фактура поставщика" } });
  const file = new File(["<Invoice/>"], "invoice-new.xml", { type: "application/xml" });
  fireEvent.change(screen.getByLabelText("Файл доказательства: supplier_eschf_xml"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить новую редакцию" }));

  expect(await screen.findByText(/Файл сохранён как доказательство для этой версии исправления/)).toBeInTheDocument();
  expect(posted).toMatchObject({ receipt_id: 92, receipt_version: 1, kind: "supplier_eschf_xml", supersedes_id: 12 });
  expect(posted?.request_key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  expect(screen.getByText(/Текущий файл · invoice-new\.xml/)).toBeInTheDocument();
  expect(screen.getByText(/invoice\.xml/)).toHaveTextContent("История");
});

it.each([
  ["oversized file", new File([new Uint8Array(10 * 1024 * 1024 + 1)], "too-large.xml", { type: "application/xml" }), /не превышать 10 МиБ/],
  ["mismatched MIME type", new File(["<Invoice/>"], "wrong.xml", { type: "text/plain" }), /соответствующим MIME-типом/],
])("rejects %s before sending it to the evidence API", async (_label, file, message) => {
  const fetcher = correctionEvidenceFetcher();
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByLabelText("Файл доказательства: supplier_eschf_xml");
  fireEvent.change(screen.getByLabelText("Файл доказательства: supplier_eschf_xml"), { target: { files: [file] } });

  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("/receipt-correction-evidence-files") && init?.method === "POST")).toBe(false);
});

it("ignores an evidence list response after the selected correction changes", async () => {
  const staleXml = deferred<unknown>();
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes("/receipt-correction-evidence-files")) {
      if (url.includes("receipt_id=92") && url.includes("supplier_eschf_xml")) return { ok: true, json: () => staleXml.promise };
      return { ok: true, json: async () => [] };
    }
    if (url.includes("correction-readiness")) {
      const receiptId = url.includes("/93/") ? 93 : 92;
      return { ok: true, json: async () => vatOnlyCorrectionReadiness(receiptId) };
    }
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("receipt-documents")) return { ok: true, json: async () => [correctionRow(92), correctionRow(93)] };
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes("receipt_id=92") && url.includes("supplier_eschf_xml"))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(await screen.findAllByText("Документы этого вида ещё не загружены.")).toHaveLength(2);
  await act(async () => {
    staleXml.resolve([inboundEvidenceFile()]);
    await staleXml.promise;
  });
  expect(screen.queryByText(/invoice\.xml/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /CORR-93/ })).toBeInTheDocument();
});

it("ignores an old upload response after selecting A, then B, then A again", async () => {
  const oldUpload = deferred<unknown>();
  let posted: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/receipt-correction-evidence-files") && init?.method === "POST") {
      posted = JSON.parse(String(init.body)) as Record<string, unknown>;
      return { ok: true, json: () => oldUpload.promise };
    }
    if (url.includes("/receipt-correction-evidence-files")) return { ok: true, json: async () => [] };
    if (url.includes("correction-readiness")) {
      const receiptId = url.includes("/93/") ? 93 : 92;
      return { ok: true, json: async () => vatOnlyCorrectionReadiness(receiptId) };
    }
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("receipt-documents")) return { ok: true, json: async () => [correctionRow(92), correctionRow(93)] };
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByLabelText("Файл доказательства: supplier_eschf_xml");
  fireEvent.change(screen.getByLabelText("Основание документа: supplier_eschf_xml"), { target: { value: "ЭСЧФ-A" } });
  fireEvent.change(screen.getByLabelText("Налоговый период: supplier_eschf_xml"), { target: { value: "2026-09" } });
  fireEvent.change(screen.getByLabelText("Комментарий к загрузке: supplier_eschf_xml"), { target: { value: "Старая загрузка для проверки гонки" } });
  const file = new File(["<Invoice>A</Invoice>"], "old-a.xml", { type: "application/xml" });
  fireEvent.change(screen.getByLabelText("Файл доказательства: supplier_eschf_xml"), { target: { files: [file] } });
  const uploadButton = screen.getAllByRole("button", { name: "Загрузить документ" })
    .find((button) => !button.hasAttribute("disabled"));
  expect(uploadButton).toBeDefined();
  fireEvent.click(uploadButton!);
  await waitFor(() => expect(posted).not.toBeNull());

  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  await screen.findAllByText("Документы этого вида ещё не загружены.");
  fireEvent.click(screen.getByRole("button", { name: /CORR-92/ }));
  await screen.findAllByText("Документы этого вида ещё не загружены.");

  const body = posted!;
  const raw = Buffer.from(String(body.data_url).split(",")[1], "base64");
  await act(async () => {
    oldUpload.resolve(inboundEvidenceFile("supplier_eschf_xml", {
      file_id: 44, receipt_id: body.receipt_id, receipt_version: body.receipt_version,
      request_key: body.request_key, tax_period: body.tax_period, reference: body.reference,
      filename: body.filename, size_bytes: raw.length,
      sha256: createHash("sha256").update(raw).digest("hex"), evidence: body.evidence,
    }));
    await oldUpload.promise;
  });
  expect(screen.queryByText(/old-a\.xml/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Файл сохранён как доказательство/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /CORR-92/ })).toBeInTheDocument();
});

it("ignores an old upload response after refreshing and reopening the same receipt revision", async () => {
  const oldUpload = deferred<unknown>();
  let posted: Record<string, unknown> | null = null;
  let listIncludesSaved = false;
  const first = inboundEvidenceFile("supplier_eschf_xml", { file_id: 12 });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/receipt-correction-evidence-files") && init?.method === "POST") {
      posted = JSON.parse(String(init.body)) as Record<string, unknown>;
      listIncludesSaved = true;
      return { ok: true, json: () => oldUpload.promise };
    }
    if (url.includes("/receipt-correction-evidence-files")) {
      if (url.includes("kind=supporting_document_pdf")) return { ok: true, json: async () => [] };
      if (!listIncludesSaved) return { ok: true, json: async () => [first] };
      const body = posted!;
      const raw = Buffer.from(String(body.data_url).split(",")[1], "base64");
      return { ok: true, json: async () => [
        { ...first, is_current: false },
        inboundEvidenceFile("supplier_eschf_xml", {
          file_id: 13, request_key: body.request_key, tax_period: body.tax_period,
          reference: body.reference, filename: body.filename, size_bytes: raw.length,
          sha256: createHash("sha256").update(raw).digest("hex"), evidence: body.evidence,
          supersedes_id: 12,
        }),
      ] };
    }
    if (url.includes("correction-readiness")) return { ok: true, json: async () => vatOnlyCorrectionReadiness() };
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("receipt-documents")) return { ok: true, json: async () => [correctionRow()] };
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText(/invoice\.xml/);
  fireEvent.change(screen.getByLabelText("Основание документа: supplier_eschf_xml"), { target: { value: "ЭСЧФ-новый" } });
  fireEvent.change(screen.getByLabelText("Налоговый период: supplier_eschf_xml"), { target: { value: "2026-09" } });
  fireEvent.change(screen.getByLabelText("Комментарий к загрузке: supplier_eschf_xml"), { target: { value: "Проверка повторного открытия накладной" } });
  const file = new File(["<Invoice>new</Invoice>"], "invoice-new.xml", { type: "application/xml" });
  fireEvent.change(screen.getByLabelText("Файл доказательства: supplier_eschf_xml"), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить новую редакцию" }));
  await waitFor(() => expect(posted).not.toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Обновить реестр" }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.includes("receipt-documents")).length).toBeGreaterThan(1));
  fireEvent.click(screen.getByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Текущий файл · invoice-new\.xml/)).toBeInTheDocument();

  const body = posted!;
  const raw = Buffer.from(String(body.data_url).split(",")[1], "base64");
  await act(async () => {
    oldUpload.resolve(inboundEvidenceFile("supplier_eschf_xml", {
      file_id: 13, request_key: body.request_key, tax_period: body.tax_period,
      reference: body.reference, filename: body.filename, size_bytes: raw.length,
      sha256: createHash("sha256").update(raw).digest("hex"), evidence: body.evidence,
      supersedes_id: 12,
    }));
    await oldUpload.promise;
  });
  expect(screen.getAllByText(/invoice-new\.xml/)).toHaveLength(1);
  expect(screen.queryByText(/Файл сохранён как доказательство/)).not.toBeInTheDocument();
});

it("requires a selected supplier and saves its directory snapshot in a new receipt", async () => {
  let submitted: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("receipt-warehouse-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 9, name: "receiving", title: "Склад приемки", is_active: true }], truncated: false,
    }) };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик из каталога", unp: "190000001" }], truncated: false,
    }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => emptyContracts(url) };
    if (url.includes("sku-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 31, code: "AKB", title: "Аккумулятор", unit: "шт" }], truncated: false,
    }) };
    if (init?.method === "POST") {
      submitted = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({ id: 41, organization_id: 7, key: submitted!.key, version: 1, status: "draft", posting: null,
        revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: submitted!.document }] }) };
    }
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByText("Выберите поставщика накладной из справочника.")).toHaveAttribute("role", "alert");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик из каталога · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByText("Выберите договор из справочника или укажите основание покупки без зарегистрированного договора.")).toHaveAttribute("role", "alert");
  explainUnregisteredContract();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByText("Выберите номенклатуру каждой строки накладной из справочника.")).toHaveAttribute("role", "alert");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await selectReceiptSku();
  fireEvent.change(screen.getByLabelText("Количество черновика 1"), { target: { value: "02.000001" } });
  fireEvent.change(screen.getByLabelText("Стоимость без НДС черновика 1"), { target: { value: "+0100.01" } });
  fireEvent.change(screen.getByLabelText("Ставка НДС % черновика 1"), { target: { value: "020" } });
  fireEvent.change(screen.getByLabelText("Сумма НДС черновика 1"), { target: { value: "020.00" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByText("Выберите склад накладной из справочника юрлица.")).toHaveAttribute("role", "alert");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await selectReceiptWarehouse();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  await waitFor(() => expect(submitted).not.toBeNull());
  expect(submitted!.document).toMatchObject({ supplier: "Поставщик из каталога", supplier_id: 19,
    supplier_unp: "190000001", contract_basis: "Поставка по счёту без зарегистрированного договора",
    warehouse: "receiving", warehouse_id: 9, warehouse_title: "Склад приемки",
    items: [{ sku_id: 31, sku: "AKB", sku_title: "Аккумулятор", unit: "шт",
      quantity: "2.000001", net_amount: "100.01", vat_rate: "20", vat_amount: "20.00" }] });
  expect(await screen.findByText("Накладная № 41: сохранена версия 1.")).toBeInTheDocument();
  expect(screen.getByLabelText("Номер первичной накладной")).toBeInTheDocument();
});

it("registers a supplier contract in the chosen company and saves its ID in the receipt", async () => {
  let receiptCommand: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("receipt-warehouse-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 9, name: "receiving", title: "Склад приемки", is_active: true }], truncated: false,
    }) };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик", unp: "190000001" }], truncated: false,
    }) };
    if (url.includes("sku-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 31, code: "AKB", title: "Аккумулятор", unit: "шт" }], truncated: false,
    }) };
    if (url.endsWith("supplier-contracts") && init?.method === "POST") {
      const data = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({ id: 50, organization_id: 7, ...data }) };
    }
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({ organization_id: 7, supplier_id: 19, items: [] }) };
    if (init?.method === "POST") {
      receiptCommand = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({ id: 41, organization_id: 7, key: receiptCommand!.key, version: 1, status: "draft", posting: null,
        revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-25", document: receiptCommand!.document }] }) };
    }
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.click(screen.getByText("Зарегистрировать договор поставщика"));
  fireEvent.change(screen.getByLabelText("Номер нового договора"), { target: { value: "SC-50" } });
  fireEvent.change(screen.getByLabelText("Название нового договора"), { target: { value: "Поставка аккумуляторов" } });
  fireEvent.change(screen.getByLabelText("Дата подписания договора"), { target: { value: "2026-01-01" } });
  fireEvent.change(screen.getByLabelText("Основание регистрации договора"), { target: { value: "Проверенный подписанный оригинал" } });
  fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать договор" }));
  expect(await screen.findByRole("option", { name: "SC-50 · Поставка аккумуляторов · ID 50" })).toBeInTheDocument();
  expect(screen.getByLabelText("Договор поставщика из справочника")).toHaveValue("50");
  await selectReceiptSku();
  await selectReceiptWarehouse();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  await waitFor(() => expect(receiptCommand).not.toBeNull());
  expect(receiptCommand!.document).toMatchObject({ supplier_id: 19, contract_id: 50, contract: "SC-50" });
  expect(receiptCommand!.document).not.toHaveProperty("contract_basis");
});

it("retries an uncertain supplier contract revocation without changing its command", async () => {
  const contract = { id: 50, organization_id: 7, supplier_id: 19, number: "SC-50",
    title: "Поставка", signed_on: "2026-01-01", expires_on: null, evidence: "Оригинал" };
  const commands: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик", unp: "190000001" }], truncated: false,
    }) };
    if (url.endsWith("supplier-contracts/50/revoke") && init?.method === "POST") {
      commands.push(String(init.body));
      if (commands.length === 1) throw new Error("Связь прервана");
      const command = JSON.parse(commands[1]);
      return { ok: true, json: async () => ({ ...contract, is_active: false,
        deactivation_key: command.key, deactivation_reason: command.reason,
        deactivated_by: "buyer", deactivated_at: "2026-09-25T10:00:00Z" }) };
    }
    if (url.includes("status=revoked")) return { ok: true, json: async () => ({
      organization_id: 7, supplier_id: 19, status: "revoked", items: [], truncated: false,
    }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({
      organization_id: 7, supplier_id: 19, items: [contract],
    }) };
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  await screen.findByRole("option", { name: "SC-50 · Поставка · ID 50" });
  fireEvent.change(screen.getByLabelText("Договор поставщика из справочника"), { target: { value: "50" } });
  fireEvent.change(screen.getByLabelText("Причина отзыва договора"), { target: { value: "Договор заменён" } });
  fireEvent.click(screen.getByRole("button", { name: "Отозвать выбранный договор" }));
  expect(await screen.findByRole("button", { name: "Повторить отзыв договора с тем же ключом" })).toBeEnabled();
  expect(screen.getByLabelText("Договор поставщика из справочника")).toHaveValue("50");
  fireEvent.click(screen.getByRole("button", { name: "Повторить отзыв договора с тем же ключом" }));
  expect(await screen.findByText(/Договор № SC-50 отозван/)).toBeInTheDocument();
  expect(commands).toHaveLength(2);
  expect(commands[1]).toBe(commands[0]);
  expect(JSON.parse(commands[0])).toMatchObject({ reason: "Договор заменён" });
  expect(screen.getByLabelText("Договор поставщика из справочника")).toHaveValue("");
  expect(screen.queryByRole("option", { name: "SC-50 · Поставка · ID 50" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Отозванные договоры поставщика (1)"));
  expect(screen.getByText("Отозвал: buyer, 2026-09-25T10:00:00Z. Причина: Договор заменён.")).toBeInTheDocument();
  expect(screen.getByLabelText("Основание покупки без зарегистрированного договора")).toHaveValue("");
  expect(fetcher.mock.calls.filter(([url, init]) => url.includes("receipt-documents") && init?.method === "POST")).toHaveLength(0);
});

it("loads revoked supplier contracts as read-only history outside the selectable list", async () => {
  const revoked = { id: 49, organization_id: 7, supplier_id: 19, number: "SC-OLD",
    title: "Прежний договор", signed_on: "2025-01-01", expires_on: null,
    evidence: "Подписанный оригинал", is_active: false, created_by: "buyer",
    created_at: "2025-01-02T09:00:00Z", deactivated_by: "chief",
    deactivated_at: "2026-09-01T12:00:00Z", deactivation_reason: "Заменён новым" };
  const older = { ...revoked, id: 48, number: "SC-EARLIER",
    deactivated_at: "2026-08-01T12:00:00Z", deactivation_reason: "Заменён ранее" };
  const fetcher = vi.fn(async (url: string) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик", unp: "190000001" }], truncated: false,
    }) };
    if (url.includes("status=revoked")) return { ok: true, json: async () => ({
      organization_id: 7, supplier_id: 19, status: "revoked",
      items: url.includes("before_id=49") ? [older] : [revoked],
      truncated: !url.includes("before_id=49"),
      next_before_at: url.includes("before_id=49") ? null : "2026-09-01T12:00:00+00:00",
      next_before_id: url.includes("before_id=49") ? null : 49,
    }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({
      organization_id: 7, supplier_id: 19, status: "active", items: [], truncated: false,
    }) };
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.click(await screen.findByText("Отозванные договоры поставщика (1)"));
  expect(screen.getByText("№ SC-OLD · Прежний договор · ID 49")).toBeInTheDocument();
  expect(screen.getByText("Отозвал: chief, 2026-09-01T12:00:00Z. Причина: Заменён новым.")).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /SC-OLD/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Показать ещё отозванные договоры" }));
  expect(await screen.findByText("№ SC-EARLIER · Прежний договор · ID 48")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Показать ещё отозванные договоры" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("before_at=2026-09-01T12%3A00%3A00%2B00%3A00")
    && url.includes("before_id=49"))).toBe(true);
});

it("warns before replacing an unsaved new receipt", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] })));
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-UNSAVED" } });
  fireEvent.click(screen.getByRole("button", { name: "Новая первичная накладная" }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-UNSAVED");
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Новая первичная накладная" }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("");
});

it("keeps the legal entity when an unsaved receipt switch is cancelled", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("unlinked-primary") ? { rows: [], next_after_id: null } : url.endsWith("receipt-organizations") ? [
      { id: 7, name: "Белакб", unp: "123456789" }, { id: 8, name: "Второе ООО", unp: "987654321" },
    ] : [] })));
  const confirm = vi.fn(() => false);
  vi.stubGlobal("confirm", confirm);
  render(<ProcurementReceipts initialOrganization="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-UNSAVED" } });
  fireEvent.change(screen.getByLabelText("Юрлицо поступления"), { target: { value: "8" } });
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("7");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-UNSAVED");
  confirm.mockReturnValue(true);
  fireEvent.change(screen.getByLabelText("Юрлицо поступления"), { target: { value: "8" } });
  expect(screen.getByLabelText("Юрлицо поступления")).toHaveValue("8");
});

it("closes a new receipt only after the server confirms its saved version", async () => {
  let releaseSave!: () => void;
  const savePending = new Promise<void>((resolve) => { releaseSave = resolve; });
  let rows: Record<string, unknown>[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("receipt-warehouse-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 9, name: "receiving", title: "Склад приемки", is_active: true }], truncated: false,
    }) };
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик из каталога", unp: "190000001" }], truncated: false,
    }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({ organization_id: 7, supplier_id: 19, items: [] }) };
    if (url.includes("sku-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 31, code: "AKB", title: "Аккумулятор", unit: "шт" }], truncated: false,
    }) };
    if (init?.method === "POST") {
      const saved = JSON.parse(String(init.body));
      await savePending;
      const row = { id: 41, organization_id: 7, key: saved.key, version: 1, status: "draft", posting: null,
        revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: saved.document }] };
      rows = [row];
      return { ok: true, json: async () => row };
    }
    return { ok: true, json: async () => rows };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  await screen.findByText("Показано 0 из 0 накладных выбранного юрлица за все даты.");
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик из каталога · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  explainUnregisteredContract();
  await selectReceiptSku();
  await selectReceiptWarehouse();
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-41" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-41");
  expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeDisabled();
  releaseSave();
  expect(await screen.findByText("Накладная № 41: сохранена версия 1, форма закрыта.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Номер первичной накладной")).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: /INV-41/ }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-41");
});

it("keeps an edited receipt open after the server rejects Save and Close", async () => {
  const original = durableReceiptDocument("INV-OLD");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "PUT"
    ? { ok: false, status: 409, json: async () => ({ detail: "Version changed" }) }
    : { ok: true, json: async () => _url.includes("purchase-ownership") ? [] : _url.includes("supplier-contracts") ? emptyContracts(_url) : [row] }));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Версия или ключ документа уже изменены");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
  expect(screen.getByRole("button", { name: "Сохранить и закрыть" })).toBeEnabled();
});

it("retries an uncertain receipt edit with the same key and closes only after confirmation", async () => {
  const original = durableReceiptDocument("INV-OLD");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  const commands: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = String(init.body);
      commands.push(body);
      const command = JSON.parse(body);
      const saved = { ...row, organization_id: 7, version: 2, revisions: [...row.revisions,
        { version: 2, request_key: command.key, actor: "buyer", created_at: "2026-09-25", document: command.document }] };
      if (commands.length === 1) throw new Error("Network response lost");
      if (commands.length === 2) return { ok: false, status: 403, json: async () => ({ detail: "Access recheck failed" }) };
      return { ok: true, json: async () => saved };
    }
    return { ok: true, json: async () => url.includes("receipt-warehouse-options") ? emptyWarehouses(url)
      : url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByText(/Результат сохранения неизвестен/)).toHaveAttribute("role", "alert");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(screen.queryByText(/форма закрыта/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" }));
  expect(await screen.findByText(/Предыдущий исход остаётся неизвестным/)).toHaveAttribute("role", "alert");
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toContain("INV-EDIT");
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" }));
  expect(await screen.findByText("Накладная № 41: сохранена версия 2, форма закрыта.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Номер первичной накладной")).not.toBeInTheDocument();
  expect(commands).toHaveLength(3);
  expect(commands[1]).toBe(commands[0]);
  expect(commands[2]).toBe(commands[0]);
  expect(JSON.parse(commands[0])).toMatchObject({ expected_version: 1, document: { invoice_reference: "INV-EDIT" } });
});

it.each(["organization", "document"])("keeps the form and durable command when a successful response tampers with %s", async (part) => {
  const original = durableReceiptDocument("INV-OLD");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const command = JSON.parse(String(init.body));
      const returnedDocument = part === "document" ? { ...command.document, invoice_reference: "FORGED" } : command.document;
      return { ok: true, json: async () => ({ ...row, organization_id: part === "organization" ? 8 : 7, version: 2,
        revisions: [...row.revisions, { version: 2, request_key: command.key, actor: "buyer", created_at: "2026-09-25", document: returnedDocument }] }) };
    }
    return { ok: true, json: async () => url.includes("receipt-warehouse-options") ? emptyWarehouses(url) : url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
  }));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Сервер не подтвердил сохранённую версию этой накладной");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toContain("INV-EDIT");
});

it("restores an unknown receipt edit after reload and retries the exact durable command", async () => {
  const original = durableReceiptDocument("INV-OLD");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  const commands: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = String(init.body); commands.push(body);
      if (commands.length === 1) throw new Error("Network response lost");
      const command = JSON.parse(body);
      return { ok: true, json: async () => ({ ...row, organization_id: 7, version: 2,
        revisions: [...row.revisions, { version: 2, request_key: command.key, actor: "buyer", created_at: "2026-09-25", document: command.document }] }) };
    }
    return { ok: true, json: async () => url.includes("receipt-warehouse-options") ? emptyWarehouses(url) : url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
  });
  vi.stubGlobal("fetch", fetcher);
  const first = render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-RELOAD" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат сохранения неизвестен");
  const durable = sessionStorage.getItem("procurement-receipt-save:v1:7");
  expect(durable).toContain("INV-RELOAD");
  first.unmount();

  render(<ProcurementReceiptDrafts org="7" initialReceipt="41" />);
  expect(await screen.findByText("Восстановлена неподтверждённая попытка сохранения. Повтор использует тот же ключ и те же реквизиты.")).toBeInTheDocument();
  expect(screen.queryByText("Загрузка накладной из ссылки…")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-RELOAD");
  const retry = screen.getByRole("button", { name: "Повторить подтверждение той же редакции" });
  await waitFor(() => expect(retry).toBeEnabled());
  fireEvent.click(retry);
  expect(await screen.findByText("Накладная № 41: сохранена версия 2, форма закрыта.")).toBeInTheDocument();
  expect(commands).toHaveLength(2);
  expect(commands[1]).toBe(commands[0]);
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toBeNull();
});

it.each([
  { caseName: "invalid JSON", journal: "{" },
  { caseName: "invalid document scalar", journal: JSON.stringify({ org: "7", receiptId: 41, version: 1,
    key: "receipt-corrupt", closeAfterSave: true, document: { ...durableReceiptDocument(), supplier: {} } }) },
])("keeps a corrupt receipt journal fail-closed with an initial link: $caseName", async ({ journal }) => {
  const document = durableReceiptDocument("INV-41");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document }] };
  sessionStorage.setItem("procurement-receipt-save:v1:7", journal);
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("receipt-warehouse-options") ? emptyWarehouses(url) : url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" initialReceipt="41" />);
  expect(await screen.findByText("Показано 1 из 1 накладных выбранного юрлица за все даты.")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Журнал сохранения накладной повреждён");
  expect(screen.queryByText("Загрузка накладной из ссылки…")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" })).toBeDisabled();
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toBe(journal);
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "PUT" || init?.method === "POST")).toBe(false);
});

it("does not turn a restored edit into a create when its source receipt is absent", async () => {
  const journal = JSON.stringify({ org: "7", receiptId: 41, version: 1, key: "receipt-missing-source",
    closeAfterSave: true, document: durableReceiptDocument("INV-MISSING") });
  sessionStorage.setItem("procurement-receipt-save:v1:7", journal);
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("receipt-warehouse-options") ? emptyWarehouses(url) : url.includes("supplier-contracts") ? emptyContracts(url) : [] }));
  vi.stubGlobal("fetch", fetcher);

  render(<ProcurementReceiptDrafts org="7" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Редактируемая накладная не найдена");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-MISSING");
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Новая первичная накладная" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Сначала подтвердите сохранённую попытку");
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toBe(journal);
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "PUT" || init?.method === "POST")).toBe(false);
});

it("blocks posting and warehouse intake until a restored edit gets its exact save receipt", async () => {
  const document = durableReceiptDocument("INV-ALREADY-VISIBLE");
  const journal = JSON.stringify({ org: "7", receiptId: 41, version: 1, key: "receipt-awaiting-ack",
    closeAfterSave: false, document });
  const row = { id: 41, version: 2, status: "draft", posting: null,
    revisions: [{ version: 2, request_key: "receipt-awaiting-ack", actor: "buyer", created_at: "2026-09-25", document }] };
  sessionStorage.setItem("procurement-receipt-save:v1:7", journal);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("receipt-warehouse-options") ? emptyWarehouses(url) : url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] })));

  render(<ProcurementReceiptDrafts org="7" policyId={1} date="2026-09-25" />);
  expect(await screen.findByText("Сначала подтвердите исход сохранения этой редакции. Проведение и складская приёмка заблокированы.")).toBeInTheDocument();
  expect(screen.queryByText(/Проводки по сохранённой версии/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Подготовить складскую приёмку" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" })).toBeEnabled();
  expect(sessionStorage.getItem("procurement-receipt-save:v1:7")).toBe(journal);
});

it.each([
  { caseName: "another receipt", returnedId: 42, returnedVersion: 2 },
  { caseName: "the old version", returnedId: 41, returnedVersion: 1 },
])("does not close when a successful HTTP response names $caseName", async ({ returnedId, returnedVersion }) => {
  const original = durableReceiptDocument("INV-OLD");
  const row = { id: 41, version: 1, status: "draft", posting: null,
    revisions: [{ version: 1, actor: "buyer", created_at: "2026-09-24", document: original }] };
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => init?.method === "PUT"
    ? { ok: true, json: async () => ({ ...row, id: returnedId, version: returnedVersion,
      revisions: returnedVersion === 1 ? row.revisions : [...row.revisions,
        { version: 2, actor: "buyer", created_at: "2026-09-24", document: original }] }) }
    : { ok: true, json: async () => _url.includes("receipt-warehouse-options") ? emptyWarehouses(_url) : _url.includes("purchase-ownership") ? [] : _url.includes("supplier-contracts") ? emptyContracts(_url) : [row] }));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Сервер не подтвердил сохранённую версию этой накладной");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
});

it("shows who changed receipt fields and their prior and new saved values", async () => {
  const first = {
    currency: "BYN", invoice_reference: "INV-41", document_date: "2026-09-23",
    operation_date: "2026-09-24", supplier: "Первый поставщик", supplier_id: 11,
    supplier_unp: "190000011", contract: "Договор А", warehouse: "Склад", warehouse_id: 4,
    warehouse_title: "Основной склад",
    explanation: "Товар", items: [{ order_id: null, sku: "AKB", unit: "шт",
      lot: "L1", quantity: "1.000000", net_amount: "100.00", vat_rate: "20.00",
      vat_amount: "20.00", vat_basis: "ОСН" }],
  };
  const second = { ...first, contract: "Договор Б", supplier: "Новый поставщик",
    supplier_id: 19, supplier_unp: "190000019",
    warehouse: "Склад возвратов", warehouse_id: 5, warehouse_title: "Склад возвратов",
    items: [{ ...first.items[0], quantity: "2.000000" }, { ...first.items[0], sku: "CHG",
      lot: "L2", vat_amount: "8.00" }] };
  const row = { id: 41, version: 2, status: "draft", posting: null, revisions: [
    { version: 1, actor: "Закупщик", created_at: "2026-09-23 10:00", document: first },
    { version: 2, actor: "Бухгалтер", created_at: "2026-09-24 11:00", document: second },
  ] };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url.includes("purchase-ownership") ? [] : [row] })));
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-41/ }));
  fireEvent.click(screen.getByText("История накладной № 41"));
  expect(screen.getByText("Версия 2 · Бухгалтер · 2026-09-24 11:00")).toBeInTheDocument();
  expect(screen.getByText("Договор накладной: было «Договор А», стало «Договор Б».")).toBeInTheDocument();
  expect(screen.getByText("Строка 1 · Количество: было «1.000000», стало «2.000000».")).toBeInTheDocument();
  expect(screen.getByText("Строка 2 · Сумма НДС: было «—», стало «8.00».")).toBeInTheDocument();
  expect(screen.getByText(/Поставщик: было «Первый поставщик · УНП 190000011 · ID 11»/)).toBeInTheDocument();
  expect(screen.getByText("Склад (справочник): было «Склад · Основной склад · ID 4», стало «Склад возвратов · Склад возвратов · ID 5»."))
    .toBeInTheDocument();
});

it("previews, confirms, and reloads the exact version-2 review-only inbound VAT workpaper", async () => {
  const evidence = workpaperEvidence();
  const { fetcher, saved, confirmedBodies } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence } });
  vi.stubGlobal("fetch", fetcher);
  const firstView = render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await waitFor(() => expect(screen.getByLabelText("Налоговый период рабочей ведомости")).toHaveValue("2026-09"));
  await screen.findByText("История рабочих ведомостей · 2026-09");

  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  expect(await screen.findByText(/Проверенный предпросмотр · 2026-09/)).toBeInTheDocument();
  expect(screen.getByText(/Строка № 501 · счёт 18\.01/)).toBeInTheDocument();
  expect(screen.getByText(/Файл № 13 · supplier_eschf_xml/)).toBeInTheDocument();
  expect(screen.getByText(/Файл № 21 · supporting_document_pdf/)).toBeInTheDocument();
  expect(screen.getByText("Подпись проверена").parentElement).toHaveTextContent("Нет");
  expect(screen.getByText("Право на вычет оценено").parentElement).toHaveTextContent("Нет");
  expect(screen.queryByRole("button", { name: /Провести|Рассчитать вычет/ })).not.toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Основание проверки бухгалтером"),
    { target: { value: "Сверены реквизиты исправления и приложенные документы." } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" }));
  expect(await screen.findByText(/Ведомость № 501 · редакция 1 · первая редакция/)).toBeInTheDocument();
  expect(screen.getByText(/Период 2026-09 · проверил accountant@example\.test · 2026-09-27T10:00:00Z/)).toBeInTheDocument();
  expect(screen.getByText(/Исходная накладная: № 81, версия 3, снимок редакции № 813/)).toBeInTheDocument();
  expect(screen.getByText(/Проведение доступно: нет/)).toBeInTheDocument();
  expect(confirmedBodies).toHaveLength(1);
  expect(JSON.parse(confirmedBodies[0])).toMatchObject({ receipt_id: 92, receipt_version: 2,
    tax_period: "2026-09", reviewer_evidence: "Сверены реквизиты исправления и приложенные документы.",
    supersedes_workpaper_id: null });
  expect(sessionStorage.getItem("inbound-vat-correction-workpaper:v1:7:92:2:2026-09")).toBeNull();
  expect([...saved.values()]).toHaveLength(1);

  firstView.unmount();
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Ведомость № 501 · редакция 1/)).toBeInTheDocument();
  expect(screen.getByText(/Подпись проверена: нет\. Факты документа проверены: нет\. Право на вычет оценено: нет\. Принято бухгалтером: нет\. Проведение доступно: нет\./)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("receipt_id=92&receipt_version=2&tax_period=2026-09"))).toBe(true);
});

it("blocks preview when a current evidence file belongs to another tax period", async () => {
  const evidence = workpaperEvidence();
  evidence.pdf.tax_period = "2026-10";
  const { fetcher } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence } });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  const period = await screen.findByLabelText("Налоговый период рабочей ведомости");
  fireEvent.change(period, { target: { value: "2026-09" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("должен совпадать с периодом каждого текущего файла");
  expect(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" })).toBeDisabled();
  expect(fetcher.mock.calls.some(([url]) => url.includes("/inbound-vat-correction-workpapers/preview"))).toBe(false);
  expect(fetcher.mock.calls.some(([url, init]) => url.endsWith("/inbound-vat-correction-workpapers") && init?.method === "POST")).toBe(false);
});

it.each([
  ["wrong organization", (value: ReturnType<typeof workpaperPreviewValue>) => ({ ...value, organization_id: 8 }), "Предпросмотр рабочей ведомости вернул повреждённую или устаревшую область данных"],
  ["wrong basis digest", (value: ReturnType<typeof workpaperPreviewValue>) => ({ ...value, basis_digest: "a".repeat(64) }), "Предпросмотр рабочей ведомости вернул повреждённую или устаревшую область данных"],
  ["account-18 line with a debit side", (value: ReturnType<typeof workpaperPreviewValue>) => {
    const basis = { ...value.basis, source_account_18_lines: [{ ...value.basis.source_account_18_lines[0], side: "debit" }] };
    return { ...value, basis, basis_digest: workpaperDigest(basis) };
  }, "Снимок рабочей ведомости не совпадает с юрлицом, исправлением или безопасным review-only контрактом"],
  ["evidence in a different period", (value: ReturnType<typeof workpaperPreviewValue>) => {
    const basis = { ...value.basis, evidence_files: value.basis.evidence_files.map((file, index) =>
      index === 1 ? { ...file, tax_period: "2026-10" } : file) };
    return { ...value, basis, basis_digest: workpaperDigest(basis) };
  }, "Снимок рабочей ведомости не совпадает с юрлицом, исправлением или безопасным review-only контрактом"],
])("rejects a preview with %s", async (_label, change, expectedError) => {
  const evidence = workpaperEvidence();
  const { fetcher } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence }, preview: () => change(workpaperPreviewValue()) });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(expectedError);
  expect(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" })).toBeDisabled();
  expect(fetcher.mock.calls.some(([url, init]) => url.endsWith("/inbound-vat-correction-workpapers") && init?.method === "POST")).toBe(false);
});

it("recovers a lost confirm response by replaying the exact saved request key and body", async () => {
  const evidence = workpaperEvidence();
  let confirmations = 0;
  const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence },
    onConfirm: (body) => {
      confirmations += 1;
      if (confirmations === 1) throw new TypeError("Connection lost after sending the request");
      return savedWorkpaper(body);
    },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  await screen.findByText(/Проверенный предпросмотр/);
  fireEvent.change(screen.getByLabelText("Основание проверки бухгалтером"),
    { target: { value: "Проверена связь документа с исходной записью." } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" }));
  expect(await screen.findByText(/Повтор используйте только с тем же ключом и телом/)).toBeInTheDocument();
  const journal = JSON.parse(sessionStorage.getItem("inbound-vat-correction-workpaper:v1:7:92:2:2026-09")!);
  const exactBody = journal.body_json as string;
  expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${journal.request_key}`))).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Повторить ту же рабочую ведомость" }));
  expect(await screen.findByText(/Ведомость № 501 · редакция 1/)).toBeInTheDocument();
  expect(confirmedBodies).toHaveLength(2);
  expect(confirmedBodies[0]).toBe(exactBody);
  expect(confirmedBodies[1]).toBe(exactBody);
  expect(JSON.parse(confirmedBodies[1]).request_key).toBe(journal.request_key);
  expect(sessionStorage.getItem("inbound-vat-correction-workpaper:v1:7:92:2:2026-09")).toBeNull();
});

it("blocks a new receipt version and navigation until the pending workpaper request is checked", async () => {
  const lostResponse = deferred<unknown>();
  let confirmations = 0;
  const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({ rows: [
    correctionRow(92, "CORR-92", 2), correctionRow(93, "CORR-93", 2),
  ], evidence: { 92: workpaperEvidence() }, onConfirm: (body) => {
    confirmations += 1;
    return confirmations === 1 ? lostResponse.promise : savedWorkpaper(body);
  } });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  await screen.findByText(/Проверенный предпросмотр/);
  fireEvent.change(screen.getByLabelText("Основание проверки бухгалтером"),
    { target: { value: "Проверена связь исправления с исходной проводкой." } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" }));
  await waitFor(() => expect(confirmedBodies).toHaveLength(1));

  const journalKey = "inbound-vat-correction-workpaper:v1:7:92:2:2026-09";
  const savedJournal = JSON.parse(sessionStorage.getItem(journalKey)!);
  const exactBody = savedJournal.body_json as string;
  expect(exactBody).toBe(confirmedBodies[0]);
  const saveButton = screen.getByRole("button", { name: "Сохранить исправление версии 2" });
  expect(saveButton).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "CORR-92-EDITED" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить исправление версии 2" }));
  expect(await screen.findByText("Сначала сверьте сохранённую рабочую ведомость; новая версия накладной заблокирована.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("CORR-92-EDITED");
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);

  await act(async () => { lostResponse.reject(new TypeError("Response lost after request was sent")); });
  expect(await screen.findByText(/Повтор используйте только с тем же ключом и телом/)).toBeInTheDocument();
  expect(sessionStorage.getItem(journalKey)).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Повторить ту же рабочую ведомость" }));
  expect(await screen.findByText(/Сохранена рабочая ведомость № 501/)).toBeInTheDocument();
  expect(confirmedBodies).toHaveLength(2);
  expect(confirmedBodies[0]).toBe(exactBody);
  expect(confirmedBodies[1]).toBe(exactBody);
  expect(sessionStorage.getItem(journalKey)).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeEnabled());
});

it("reports an older workpaper journal and refuses a new receipt version", async () => {
  const journal = pendingWorkpaperJournal();
  sessionStorage.setItem(journal.key, journal.journalJson);
  const { fetcher } = inboundVatWorkpaperFetcher({ rows: [
    correctionRowWithHistory(92, 2), correctionRow(93, "CORR-93", 2),
  ] });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("несверенный запрос рабочей ведомости версии 1");
  expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("CORR-92");
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
});

it.each([true, false])("invalidates delayed older-journal recovery after same-card reopen=%s, but not period setup", async (reopen) => {
  const journal = pendingWorkpaperJournal();
  sessionStorage.setItem(journal.key, journal.journalJson);
  let resolveByRequest!: (value: unknown) => void;
  const byRequestResponse = new Promise<unknown>((resolve) => { resolveByRequest = resolve; });
  let resolveEvidence!: () => void;
  const evidenceGate = new Promise<void>((resolve) => { resolveEvidence = resolve; });
  const { fetcher: baseFetcher } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2)],
    onByRequest: () => byRequestResponse,
  });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("receipt-correction-evidence-files")) await evidenceGate;
    return baseFetcher(url, init);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(screen.getByLabelText("Налоговый период рабочей ведомости")).toHaveValue("");
  fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${journal.body.request_key}`))).toBe(true));

  resolveEvidence();
  await waitFor(() => expect(screen.getByLabelText("Налоговый период рабочей ведомости")).toHaveValue("2026-09"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled());
  if (reopen) {
    fireEvent.click(screen.getByRole("button", { name: /CORR-92/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled());
  }

  await act(async () => {
    resolveByRequest(savedWorkpaper(journal.body));
    await new Promise((resolve) => setTimeout(resolve, 40));
  });
  expect(fetcher.mock.calls.filter(([url]) => url.includes(`/by-request/${journal.body.request_key}`))).toHaveLength(1);
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
  if (reopen) {
    expect(sessionStorage.getItem(journal.key)).toBe(journal.journalJson);
    expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled();
    expect(screen.queryByText(/Сохранена рабочая ведомость № 501/)).not.toBeInTheDocument();
  } else {
    expect(await screen.findByText(/Сохранена рабочая ведомость № 501/)).toBeInTheDocument();
    expect(sessionStorage.getItem(journal.key)).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeEnabled());
  }
});

it("reconciles a saved older workpaper through by-request without changing the open receipt", async () => {
  const journal = pendingWorkpaperJournal();
  sessionStorage.setItem(journal.key, journal.journalJson);
  const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2)],
    onByRequest: (key) => key === journal.body.request_key ? savedWorkpaper(journal.body) : undefined,
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  await waitFor(() => expect(sessionStorage.getItem(journal.key)).toBeNull());
  expect(await screen.findByText(/Сохранена рабочая ведомость № 501, редакция 1, для версии накладной 1/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${journal.body.request_key}`))).toBe(true);
  expect(confirmedBodies).toHaveLength(0);
  expect(sessionStorage.getItem(journal.key)).toBeNull();
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("CORR-92");
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeEnabled();
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
});

it("clears an absent older journal only after the exact stale-revision 409", async () => {
  const journal = pendingWorkpaperJournal();
  sessionStorage.setItem(journal.key, journal.journalJson);
  const { fetcher, confirmedBodies, saved } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2)],
    onConfirm: () => { throw Object.assign(new Error("Workpaper requires the exact current correction draft revision"), { status: 409 }); },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  expect(await screen.findByText(/Запрос рабочей ведомости для версии 1 не создал запись: сервер подтвердил устаревшую редакцию/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${journal.body.request_key}`))).toBe(true);
  expect(confirmedBodies).toEqual([journal.bodyJson]);
  expect(saved.size).toBe(0);
  expect(sessionStorage.getItem(journal.key)).toBeNull();
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeEnabled();
});

it("reconciles all older journals in sequence and unlocks only when storage is empty", async () => {
  const first = pendingWorkpaperJournal(1, "2026-08", "95bd12f3-a45c-4b89-b005-2f9fa22c38a1");
  const second = pendingWorkpaperJournal(1, "2026-09", "c3f1eb9e-0d8d-4db5-9de6-34d78d5598aa");
  sessionStorage.setItem(second.key, second.journalJson);
  sessionStorage.setItem(first.key, first.journalJson);
  const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2)],
    onByRequest: (key) => key === first.body.request_key ? savedWorkpaper(first.body) : undefined,
    onConfirm: () => { throw Object.assign(new Error("Workpaper requires the exact current correction draft revision"), { status: 409 }); },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(new RegExp(first.body.request_key))).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  expect(await screen.findByText(/Сохранена рабочая ведомость № 501/)).toBeInTheDocument();
  expect(sessionStorage.getItem(first.key)).toBeNull();
  expect(sessionStorage.getItem(second.key)).toBe(second.journalJson);
  expect(await screen.findByText(new RegExp(second.body.request_key))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("CORR-92");

  await waitFor(() => expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  expect(await screen.findByText(/Запрос рабочей ведомости для версии 1 не создал запись: сервер подтвердил устаревшую редакцию/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${first.body.request_key}`))).toBe(true);
  expect(fetcher.mock.calls.some(([url]) => url.includes(`/by-request/${second.body.request_key}`))).toBe(true);
  expect(confirmedBodies).toEqual([second.bodyJson]);
  expect(sessionStorage.getItem(first.key)).toBeNull();
  expect(sessionStorage.getItem(second.key)).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeEnabled());
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
});

it("keeps the second older journal hidden behind an ambiguous first journal", async () => {
  const first = pendingWorkpaperJournal(1, "2026-08", "95bd12f3-a45c-4b89-b005-2f9fa22c38a1");
  const second = pendingWorkpaperJournal(1, "2026-09", "c3f1eb9e-0d8d-4db5-9de6-34d78d5598aa");
  sessionStorage.setItem(first.key, first.journalJson);
  sessionStorage.setItem(second.key, second.journalJson);
  const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2)],
    onByRequest: () => { throw new TypeError("Network unavailable"); },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  expect(await screen.findByText(/Сохранённый ключ и тело оставлены без изменений/)).toBeInTheDocument();
  expect(screen.getByText(new RegExp(first.body.request_key))).toBeInTheDocument();
  expect(screen.queryByText(new RegExp(second.body.request_key))).not.toBeInTheDocument();
  expect(sessionStorage.getItem(first.key)).toBe(first.journalJson);
  expect(sessionStorage.getItem(second.key)).toBe(second.journalJson);
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
  expect(fetcher.mock.calls.filter(([url]) => url.includes("/by-request/")).map(([url]) => url)).toHaveLength(1);
  expect(confirmedBodies).toHaveLength(0);
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
});

it("shows a corrupt next journal after resolving the first even when readiness returns 403", async () => {
  const first = pendingWorkpaperJournal(1, "2026-08", "95bd12f3-a45c-4b89-b005-2f9fa22c38a1");
  const second = pendingWorkpaperJournal(1, "2026-09", "c3f1eb9e-0d8d-4db5-9de6-34d78d5598aa");
  const corruptJournal = "{malformed journal";
  sessionStorage.setItem(first.key, first.journalJson);
  sessionStorage.setItem(second.key, corruptJournal);
  const { fetcher: baseFetcher, confirmedBodies } = inboundVatWorkpaperFetcher({
    rows: [correctionRowWithHistory(92, 2), correctionRow(93, "CORR-93", 2)],
    onByRequest: (key) => key === first.body.request_key ? savedWorkpaper(first.body) : undefined,
  });
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => url.includes("correction-readiness")
    ? { ok: false, status: 403, json: async () => ({ detail: "Accountant access required" }) }
    : baseFetcher(url, init));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Предпросмотр и подтверждение доступны только при точной VAT-only готовности/)).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("correction-readiness"))).toBe(true);
  fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
  expect(await screen.findByText((_, element) => element?.getAttribute("role") === "alert"
    && element.textContent?.includes(second.key) === true)).toBeInTheDocument();
  expect(sessionStorage.getItem(first.key)).toBeNull();
  expect(sessionStorage.getItem(second.key)).toBe(corruptJournal);
  expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("CORR-92");
  expect(confirmedBodies).toHaveLength(0);
  expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
    && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
});

it.each(["by-request 403", "by-request 500", "by-request network", "malformed saved response", "other replay conflict"])(
  "keeps an older journal blocked on %s", async (failureMode) => {
    const journal = pendingWorkpaperJournal();
    sessionStorage.setItem(journal.key, journal.journalJson);
    const { fetcher, confirmedBodies } = inboundVatWorkpaperFetcher({
      rows: [correctionRowWithHistory(92, 2)],
      onByRequest: () => {
        if (failureMode === "by-request 403") throw Object.assign(new Error("Accountant access required"), { status: 403 });
        if (failureMode === "by-request 500") throw Object.assign(new Error("Temporary server failure"), { status: 500 });
        if (failureMode === "by-request network") throw new TypeError("Network unavailable");
        if (failureMode === "malformed saved response") return savedWorkpaper(journal.body, { organizationId: 8 });
        return undefined;
      },
      onConfirm: () => { throw Object.assign(new Error("Different conflict"), { status: 409 }); },
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ProcurementReceiptDrafts org="7" />);
    fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Сверить рабочую ведомость версии 1" }));
    if (failureMode === "by-request 403")
      expect(await screen.findByText(/Доступ к восстановлению запрещён \(403\)/)).toBeInTheDocument();
    else expect(await screen.findByText(/Сохранённый ключ и тело оставлены без изменений/)).toBeInTheDocument();
    expect(sessionStorage.getItem(journal.key)).not.toBeNull();
    expect(screen.getByRole("button", { name: "Сохранить исправление версии 2" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Сверить рабочую ведомость версии 1" })).toBeEnabled();
    expect(fetcher.mock.calls.some(([url, init]) => url.includes("receipt-documents")
      && ["POST", "PUT", "PATCH"].includes(String(init?.method)))).toBe(false);
    expect(confirmedBodies).toHaveLength(failureMode === "other replay conflict" ? 1 : 0);
  },
);

it("keeps a pending journal when a saved response is foreign or has an unsafe flag", async () => {
  const evidence = workpaperEvidence();
  const { fetcher } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence },
    onConfirm: (body) => savedWorkpaper(body, { organizationId: 8, flags: { signature_verified: true } }),
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  await screen.findByText(/Проверенный предпросмотр/);
  fireEvent.change(screen.getByLabelText("Основание проверки бухгалтером"),
    { target: { value: "Проверен комплект приложенных документов." } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить ведомость (только review)" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждает точный запрос, источник или review-only ограничения");
  expect(sessionStorage.getItem("inbound-vat-correction-workpaper:v1:7:92:2:2026-09")).not.toBeNull();
});

it("ignores an old preview after opening the same card again and after A-to-B-to-A", async () => {
  const oldPreview = deferred<unknown>();
  const rows = [correctionRow(92, "CORR-92", 2), correctionRow(93, "CORR-93", 2)];
  let aPreviewCalls = 0;
  const { fetcher } = inboundVatWorkpaperFetcher({ rows,
    preview: (body) => {
      if (Number(body.receipt_id) !== 92) return workpaperPreviewValue(Number(body.receipt_id), 2, String(body.tax_period), { lineId: 603 });
      aPreviewCalls += 1;
      return aPreviewCalls === 1 ? oldPreview.promise : workpaperPreviewValue(92, 2, String(body.tax_period), { lineId: 602 });
    },
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.includes("/inbound-vat-correction-workpapers/preview"))).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: /CORR-92/ }));
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: /CORR-92/ }));
  await screen.findByText("История рабочих ведомостей · 2026-09");
  fireEvent.click(screen.getByRole("button", { name: "Предпросмотр рабочей ведомости" }));
  expect(await screen.findByText(/Строка № 602 · счёт 18\.01/)).toBeInTheDocument();
  await act(async () => { oldPreview.resolve(workpaperPreviewValue(92, 2, "2026-09", { lineId: 601 })); await oldPreview.promise; });
  expect(screen.getByText(/Строка № 602 · счёт 18\.01/)).toBeInTheDocument();
  expect(screen.queryByText(/Строка № 601 · счёт 18\.01/)).not.toBeInTheDocument();
});

it("shows a 403 from the workpaper history endpoint without enabling confirmation", async () => {
  const evidence = workpaperEvidence();
  const { fetcher } = inboundVatWorkpaperFetcher({ evidence: { 92: evidence } });
  fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.includes("/inbound-vat-correction-workpapers?") )
      return { ok: false, status: 403, json: async () => ({ detail: "Accountant or chief access required" }) };
    return (await (inboundVatWorkpaperFetcher({ evidence: { 92: evidence } }).fetcher(url, init)));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("История ведомостей не подтверждена");
  expect(screen.getByRole("alert")).toHaveTextContent("403");
  expect(screen.queryByRole("button", { name: /Провести|Рассчитать вычет/ })).not.toBeInTheDocument();
});
