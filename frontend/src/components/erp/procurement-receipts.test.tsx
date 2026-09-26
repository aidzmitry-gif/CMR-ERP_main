import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function explainUnregisteredContract() {
  fireEvent.change(screen.getByLabelText("Основание покупки без зарегистрированного договора"),
    { target: { value: "Поставка по счёту без зарегистрированного договора" } });
}

function emptyContracts(url: string) {
  return { organization_id: 7, supplier_id: 19,
    status: url.includes("status=revoked") ? "revoked" : "active", items: [], truncated: false };
}

function durableReceiptDocument(invoiceReference = "INV-DURABLE") {
  return {
    currency: "BYN", invoice_reference: invoiceReference, document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19,
    supplier_unp: "190000001", contract: "Без договора", contract_basis: "Поставка без договора",
    warehouse: "Основной склад", explanation: "Товар", items: [{ order_id: null, sku_id: 31,
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

function correctionRow(id = 92, invoiceReference = `CORR-${id}`) {
  const document = { currency: "BYN", invoice_reference: invoiceReference, document_date: "2026-09-24",
    operation_date: "2026-09-24", supplier: "Поставщик", supplier_id: 19, supplier_unp: "190000001",
    contract: "D-1", contract_id: 50, contract_basis: null, warehouse: "Основной", explanation: "Исправление", items: [] };
  return { id, organization_id: 7, version: 1, status: "draft", posting: null,
    correction_of: { receipt_id: 81, version: 3, entry_id: 42 },
    revisions: [{ version: 1, actor: "accountant", created_at: "2026-09-26", document }] };
}

function vatOnlyCorrectionReadiness(receiptId = 92) {
  return correctionReadiness(receiptId, { vat_change: true, no_difference: false }, {
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
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
        : url.includes("supplier-contracts") ? emptyContracts(url) : url.includes("purchase-ownership") ? [] : rows }));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /CORR-92/ }));
  expect(await screen.findByText(/Не удалось подтвердить проверку для выбранного юрлица и версии/))
    .toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByText(/Изменение количества или склада не выявлено/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-93/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByText(/Различий между исходной накладной и исправлением не выявлено/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /CORR-94/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Проведение и движение WMS остаются недоступны");
  expect(screen.queryByRole("button", { name: /Провести/ })).not.toBeInTheDocument();
});

it("ignores readiness responses made stale by changing the selected correction or organization", async () => {
  const oldDocumentResponse = deferred<unknown>(), oldOrganizationResponse = deferred<unknown>();
  const rows = [correctionRow(92), correctionRow(93)];
  const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/92/correction-readiness")
    ? oldDocumentResponse.promise : url.includes("/93/correction-readiness") ? oldOrganizationResponse.promise
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
  expect(await screen.findByRole("alert")).toHaveTextContent("Проведение и движение WMS остаются недоступны");
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

  expect(await screen.findByRole("alert")).toHaveTextContent("Просмотр и загрузка доказательств заблокированы");
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
    if (url.includes("supplier-options")) return { ok: true, json: async () => ({
      organization_id: 7, items: [{ id: 19, name: "Поставщик из каталога", unp: "190000001" }], truncated: false,
    }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({ organization_id: 7, supplier_id: 19, items: [] }) };
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
  expect(screen.getByRole("alert")).toHaveTextContent("Выберите поставщика накладной из справочника");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.change(screen.getByLabelText("Поиск поставщика накладной"), { target: { value: "Поставщик" } });
  await screen.findByRole("option", { name: "Поставщик из каталога · 190000001" });
  fireEvent.change(screen.getByLabelText("Поставщик накладной из справочника"), { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Выберите договор из справочника");
  explainUnregisteredContract();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Выберите номенклатуру каждой строки накладной из справочника");
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await selectReceiptSku();
  fireEvent.change(screen.getByLabelText("Количество черновика 1"), { target: { value: "02.000001" } });
  fireEvent.change(screen.getByLabelText("Стоимость без НДС черновика 1"), { target: { value: "+0100.01" } });
  fireEvent.change(screen.getByLabelText("Ставка НДС % черновика 1"), { target: { value: "020" } });
  fireEvent.change(screen.getByLabelText("Сумма НДС черновика 1"), { target: { value: "020.00" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить первичную накладную" }));
  await waitFor(() => expect(submitted).not.toBeNull());
  expect(submitted!.document).toMatchObject({ supplier: "Поставщик из каталога", supplier_id: 19,
    supplier_unp: "190000001", contract_basis: "Поставка по счёту без зарегистрированного договора",
    items: [{ sku_id: 31, sku: "AKB", sku_title: "Аккумулятор", unit: "шт",
      quantity: "2.000001", net_amount: "100.01", vat_rate: "20", vat_amount: "20.00" }] });
  expect(await screen.findByText("Накладная № 41: сохранена версия 1.")).toBeInTheDocument();
  expect(screen.getByLabelText("Номер первичной накладной")).toBeInTheDocument();
});

it("registers a supplier contract in the chosen company and saves its ID in the receipt", async () => {
  let receiptCommand: Record<string, unknown> | null = null;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
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
    return { ok: true, json: async () => url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementReceiptDrafts org="7" />);
  fireEvent.click(await screen.findByRole("button", { name: /INV-OLD/ }));
  fireEvent.change(screen.getByLabelText("Номер первичной накладной"), { target: { value: "INV-EDIT" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Результат сохранения неизвестен");
  expect(screen.getByLabelText("Номер первичной накладной")).toHaveValue("INV-EDIT");
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  expect(screen.queryByText(/форма закрыта/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Предыдущий исход остаётся неизвестным");
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
    return { ok: true, json: async () => url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
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
    return { ok: true, json: async () => url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] };
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
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение той же редакции" }));
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
    url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] }));
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
    url.includes("supplier-contracts") ? emptyContracts(url) : [] }));
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
    url.includes("purchase-ownership") ? [] : url.includes("supplier-contracts") ? emptyContracts(url) : [row] })));

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
    : { ok: true, json: async () => _url.includes("purchase-ownership") ? [] : _url.includes("supplier-contracts") ? emptyContracts(_url) : [row] }));
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
    supplier_unp: "190000011", contract: "Договор А", warehouse: "Склад",
    explanation: "Товар", items: [{ order_id: null, sku: "AKB", unit: "шт",
      lot: "L1", quantity: "1.000000", net_amount: "100.00", vat_rate: "20.00",
      vat_amount: "20.00", vat_basis: "ОСН" }],
  };
  const second = { ...first, contract: "Договор Б", supplier: "Новый поставщик",
    supplier_id: 19, supplier_unp: "190000019",
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
});
