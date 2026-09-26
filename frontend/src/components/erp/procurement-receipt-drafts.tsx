"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { fetchProcurementSkus, fetchProcurementSuppliers, type ProcurementSkuOption, type ProcurementSupplierOption } from "@/lib/procurement-machine";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";
import { ProcurementReceiptPosting, type ReceiptAccount } from "./procurement-receipt-posting";

const item = () => ({ order_id: null as number | null, sku_id: null as number | null, sku_title: null as string | null, sku: "", unit: null as string | null, lot: "", quantity: "", net_amount: "", vat_amount: "", vat_rate: "", vat_basis: "" });
const blank = () => ({ currency: "BYN", invoice_reference: "", document_date: "", operation_date: "", supplier: "", supplier_id: null as number | null, supplier_unp: null as string | null, contract: "", contract_id: null as number | null, contract_basis: null as string | null, warehouse: "", explanation: "", items: [item()] });
type Document = ReturnType<typeof blank>;
type SupplierContract = { id: number; organization_id: number; supplier_id: number; number: string; title: string; signed_on: string; expires_on: string | null; evidence: string; is_active?: boolean; created_by?: string; created_at?: string; deactivated_by?: string | null; deactivated_at?: string | null; deactivation_reason?: string | null };
type ContractHistoryPage = { organization_id: number; supplier_id: number; status: string; items: SupplierContract[]; truncated: boolean; next_before_at: string | null; next_before_id: number | null };
type ContractHistoryCursor = { at: string; id: number };
type Receipt = { id: number; key?: string; version: number; status?: string; posting?: { entry_id: number; version: number } | null; revisions: { version: number; request_key?: string | null; actor: string; created_at: string; document: Document }[] };
type PendingSave = { org: string; receiptId: number | null; version: number; key: string; document: Document; closeAfterSave: boolean };
type PendingContractRevoke = { org: string; supplierId: number; contractId: number; key: string; reason: string };
type OwnedOrder = { kind: string; source_id: number; snapshot: { number: string; supplier: string } };
const fields = [["invoice_reference", "Номер первичной накладной"], ["document_date", "Дата первичной накладной"], ["operation_date", "Дата поступления"], ["contract", "Договор накладной"], ["warehouse", "Склад накладной"], ["explanation", "Содержание накладной"]] as const;
const itemFields = [["lot", "Партия"], ["quantity", "Количество"], ["net_amount", "Стоимость без НДС"], ["vat_rate", "Ставка НДС %"], ["vat_amount", "Сумма НДС"], ["vat_basis", "Основание НДС"]] as const;
const itemHistoryFields = [["order_id", "Заказ поставщику"], ["order_line_id", "Строка заказа"], ["sku_id", "ID номенклатуры"], ["sku_title", "Название номенклатуры"], ["sku", "Код номенклатуры"], ["unit", "Единица измерения"], ...itemFields] as const;
const shown = (value: unknown) => value === null || value === undefined || value === "" ? "—" : String(value);
const supplierSnapshot = (document: Document) => `${shown(document.supplier)} · УНП ${shown(document.supplier_unp)} · ${document.supplier_id ? `ID ${document.supplier_id}` : "без связи со справочником"}`;
function revisionChanges(previous: Document, current: Document) {
  const changes: { label: string; before: string; after: string }[] = [];
  const add = (label: string, before: unknown, after: unknown) => {
    if (JSON.stringify(before) !== JSON.stringify(after)) changes.push({ label, before: shown(before), after: shown(after) });
  };
  add("Валюта", previous.currency, current.currency);
  for (const [field, label] of fields) add(label, previous[field], current[field]);
  add("Поставщик", supplierSnapshot(previous), supplierSnapshot(current));
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
  const [contracts, setContracts] = useState<SupplierContract[]>([]), [contractError, setContractError] = useState("");
  const [revokedState, setRevokedState] = useState<{ context: string; items: SupplierContract[]; next: ContractHistoryCursor | null; loading: boolean; error: string }>({ context: "", items: [], next: null, loading: false, error: "" });
  const [newContract, setNewContract] = useState({ number: "", title: "", signed_on: "", expires_on: "", evidence: "" });
  const [contractBusy, setContractBusy] = useState(false);
  const [contractRevokeReason, setContractRevokeReason] = useState("");
  const [contractRevokeUncertain, setContractRevokeUncertain] = useState(false);
  const [skuSearch, setSkuSearch] = useState("");
  const [skuOptions, setSkuOptions] = useState<ProcurementSkuOption[]>([]);
  const [skuError, setSkuError] = useState("");
  const [selected, setSelected] = useState<Receipt | null>(null), [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [editorOpen, setEditorOpen] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [reload, setReload] = useState(0);
  const [loadedKey, setLoadedKey] = useState("");
  const pending = useRef<PendingSave | null>(null), active = useRef(true);
  const pendingContractRevoke = useRef<PendingContractRevoke | null>(null);
  const contractFetchVersion = useRef(0), supplierContext = useRef("");
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
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
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
      if (initialReceipt !== undefined && !initialOpened.current) {
        initialOpened.current = true;
        setInitialLoading(false);
        const row = data.find(row => String(row.id) === initialReceipt);
        if (row) {
          setSelected(row); setDocument(structuredClone(row.revisions.at(-1)!.document));
          setEditorOpen(true);
          pending.current = null; setUncertain(false); setError(""); setNotice("");
        }
        else setError("Накладная из ссылки не найдена в выбранном юрлице.");
      }
    } }).catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [path, listKey, initialReceipt]);
  function open(row: Receipt | null) {
    if (!confirmDiscard()) return;
    setContracts([]); setContractError("");
    setSelected(row); setDocument(row ? structuredClone(row.revisions.at(-1)!.document) : blank());
    setEditorOpen(true);
    pending.current = null; setUncertain(false); setError(""); setNotice("");
  }
  function save(closeAfterSave = false) {
    if (selected?.posting || busy || uncertain || pending.current) return;
    if (!document.supplier_id || document.supplier_unp == null) {
      setError("Выберите поставщика накладной из справочника."); return;
    }
    if (!document.contract_id && !document.contract_basis?.trim()) {
      setError("Выберите договор из справочника или укажите основание покупки без зарегистрированного договора."); return;
    }
    if (document.items.some(row => !row.sku_id || !row.sku_title || !row.unit)) {
      setError("Выберите номенклатуру каждой строки накладной из справочника."); return;
    }
    const command: PendingSave = { org, receiptId: selected?.id ?? null, version: selected?.version ?? 0,
      key: crypto.randomUUID(), document: structuredClone(document), closeAfterSave };
    pending.current = command;
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
      if (!Number.isSafeInteger(row?.id) || row.id < 1 || !Number.isSafeInteger(row.version)
        || row.version !== command.version + 1
        || revision?.version !== row.version || !revision.document
        || (command.receiptId ? row.id !== command.receiptId || revision.request_key !== command.key
          : row.key !== command.key)) {
        throw new Error("Сервер не подтвердил сохранённую версию этой накладной. Форма оставлена открытой.");
      }
      if (!active.current) return;
      pending.current = null; setUncertain(false);
      setSelected(command.closeAfterSave ? null : row);
      setDocument(command.closeAfterSave ? blank() : structuredClone(revision.document));
      setEditorOpen(!command.closeAfterSave);
      setRows((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      setNotice(`Накладная № ${row.id}: сохранена версия ${row.version}${command.closeAfterSave ? ", форма закрыта" : ""}.`);
    } catch (e) { if (active.current) {
      const status = (e as Error & { status?: number }).status;
      if (status === undefined || status >= 500) {
        setUncertain(true);
        setError(`${(e as Error).message} Результат сохранения неизвестен. Повторите подтверждение той же редакции.`);
      } else {
        pending.current = null; setUncertain(false); setError((e as Error).message);
      }
    } }
    finally { if (active.current) setBusy(false); }
  }
  function retryPending() {
    if (busy || !pending.current || pending.current.org !== org) return;
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
  if (initialLoading) return <section className="space-y-3 rounded-xl border border-line bg-surface p-4"><p role="status">Загрузка накладной из ссылки…</p>{error && <><p role="alert">{error}</p><Button onClick={() => setReload(value => value + 1)}>Повторить загрузку накладной</Button></>}</section>;
  return <section className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Реестр первичных накладных</h2>
    <p className="text-sm text-muted">Суммы в BYN по документу поставщика. Сохранение черновика не создаёт проводки и складские движения.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {orderError && <p role="alert">{orderError}</p>}
    <fieldset disabled={busy} className="space-y-3">
      {uncertain && <div className="rounded border border-accent p-3"><p>Форма сохранена до сверки результата. Повтор отправит те же реквизиты и ключ операции.</p><Button onClick={retryPending}>Повторить подтверждение той же редакции</Button></div>}
      <div className="flex gap-2"><Button variant="secondary" onClick={() => open(null)}>Новая первичная накладная</Button><Button variant="secondary" onClick={() => setReload((v) => v + 1)}>Обновить реестр</Button></div>
      <div className="grid gap-3 md:grid-cols-2"><label>Поиск по номеру, поставщику или дате<Input aria-label="Поиск накладных" value={query} onChange={(e) => setQuery(e.target.value)} /></label><label>Статус накладной<Select aria-label="Статус накладной" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">Все</option><option value="draft">Черновики</option><option value="posted">Проведённые</option></Select></label></div>
      {!listLoaded && !error && <p role="status">Загрузка реестра накладных…</p>}
      {listLoaded && <p className="text-sm text-muted">Показано {visible.length} из {rows.length} накладных выбранного юрлица за все даты.</p>}
      {listLoaded && <ul className="divide-y divide-line">{visible.map((row) => {
        const source = row.revisions.at(-1)!.document;
        return <li key={row.id} className="flex flex-wrap items-center gap-2 py-2">
          <Button variant="secondary" onClick={() => open(row)}>{source.invoice_reference} · {source.document_date} · {source.supplier}</Button>
          <span className="text-sm">{row.posting ? "Проведена" : "Черновик"} · версия {row.version}</span>
          {row.posting && <Link className="text-sm text-accent underline" href={`/erp/procurement/receipts/posted/${row.posting.entry_id}?org=${org}`}>Открыть проведённую накладную</Link>}
        </li>;
      })}</ul>}
      {listLoaded && !visible.length && <p className="text-sm text-muted">Накладных по выбранному фильтру нет.</p>}
      {selected?.posting && <p role="status">Проведена · проводка № {selected.posting.entry_id}. Первичные данные доступны для просмотра.</p>}
      {contractRevokeUncertain && <Button variant="secondary" disabled={contractBusy || pendingContractRevoke.current?.org !== org} onClick={() => { if (pendingContractRevoke.current) void submitContractRevoke(pendingContractRevoke.current); }}>Повторить отзыв договора с тем же ключом</Button>}
      {editorOpen && <fieldset disabled={Boolean(selected?.posting) || uncertain || contractBusy || contractRevokeUncertain} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">{fields.map(([field, label]) => <label key={field}>{label}<Input type={field.endsWith("date") ? "date" : "text"} disabled={field === "contract" && Boolean(document.contract_id)} value={document[field]} onChange={(e) => setDocument({ ...document, [field]: e.target.value })} /></label>)}</div>
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
      <div className="flex gap-2"><Button variant="secondary" disabled={document.items.length >= 300} onClick={() => setDocument({ ...document, items: [...document.items, item()] })}>Добавить строку накладной</Button><Button onClick={() => void save()}>{selected ? `Сохранить исправление версии ${selected.version}` : "Сохранить первичную накладную"}</Button><Button variant="secondary" onClick={() => void save(true)}>Сохранить и закрыть</Button></div>
      </fieldset>}
    </fieldset>
    {selected && !selected.posting && (dirty ? <p>Сохраните изменения накладной перед расчётом проводок.</p> : !document.supplier_id ? <p>Сопоставьте поставщика со справочником перед проведением.</p> : document.items.some(row => !row.sku_id) ? <p>Сопоставьте все товары накладной со справочником перед проведением.</p> : <ProcurementReceiptPosting key={`${selected.id}/${selected.version}/${date}/${policyId}`} blocked={busy} org={org} receiptId={selected.id} version={selected.version} items={document.items} accounts={accounts} policyId={policyId} date={date} onBusy={(value) => { if (active.current) setBusy(value); }} onPosted={(entryId) => {
      if (!active.current) return;
      setSelected((current) => current?.id === selected.id ? { ...current, status: "posted", posting: { entry_id: entryId, version: selected.version } } : current);
      setRows((current) => current.map((row) => row.id === selected.id ? { ...row, status: "posted", posting: { entry_id: entryId, version: selected.version } } : row));
      setReload((value) => value + 1); onPosted?.();
    }} />)}
    {selected && !dirty && document.supplier_id && document.items.every(row => row.sku_id) && <Link className="text-accent underline" href={`/erp/wms/receipts/from-primary?org=${org}&receipt=${selected.id}&version=${selected.version}`}>Подготовить складскую приёмку</Link>}
    {selected && <details><summary>История накладной № {selected.id}</summary>{selected.revisions.map((row, index) => {
      const changes = index ? revisionChanges(selected.revisions[index - 1].document, row.document) : [];
      return <article key={row.version} className="border-b border-line py-3">
        <h3>Версия {row.version} · {row.actor} · {row.created_at}</h3>
        {index ? <div><h4>Изменения редакции</h4>{changes.length
          ? <ul>{changes.map((change, i) => <li key={`${change.label}:${i}`}>{change.label}: было «{change.before}», стало «{change.after}».</li>)}</ul>
          : <p>Реквизиты не изменились.</p>}</div> : <p>Исходная редакция.</p>}
        <details><summary>Полный снимок версии {row.version}</summary>
          <dl>{fields.map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{row.document[field]}</dd></div>)}<div><dt>Поставщик накладной</dt><dd>{row.document.supplier} · {row.document.supplier_unp || "УНП не указан"} · {row.document.supplier_id ? `ID ${row.document.supplier_id}` : "связь со справочником неизвестна"}</dd></div></dl>
          {row.document.items.map((r, i) => <p key={i}>{r.sku} · {r.sku_title || "название неизвестно"} · {r.sku_id ? `SKU ID ${r.sku_id}` : "связь со справочником неизвестна"}{r.order_id ? ` · заказ № ${r.order_id}` : ""} · партия {r.lot} · {r.quantity} {r.unit ?? "(единица не указана)"} · без НДС {r.net_amount} BYN · НДС {r.vat_rate}% / {r.vat_amount} BYN · {r.vat_basis}</p>)}
        </details>
      </article>;
    })}</details>}
  </section>;
}
