"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { canonical } from "@/lib/procurement-machine";

type CorrectionOf = { receipt_id: number; version: number; entry_id: number };
type Source = {
  organization_id: number;
  receipt_id: number;
  entry_id: number;
  version: number;
  document: {
    invoice_reference: string;
    document_date: string;
    operation_date: string;
    supplier: string;
    supplier_id?: number | null;
    supplier_unp?: string | null;
    contract: string;
    warehouse: string;
    explanation: string;
    items: { sku: string; lot: string; quantity: string; net_amount: string; vat_amount: string; vat_rate: string; vat_basis: string; order_id?: number | null }[];
  };
};
type CorrectionCommand = { org: string; originalReceiptId: number; expectedVersion: number; expectedEntryId: number; key: string; body: string };
type CorrectionResponse = { id: number; organization_id: number; key: string; version: number; status: string; posting: null; correction_of: CorrectionOf; revisions: { version: number; document: Source["document"] }[] };
type CorrectionState = { context: string; command?: CorrectionCommand; busy: boolean; uncertain: boolean; blocked: boolean; error?: string; created?: { id: number; version: number } };

const positiveId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const correctionJournalKey = (org: string, receiptId: number) => `procurement-receipt-correction:v1:${org}:${receiptId}`;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function validSource(value: unknown, org: string, entry: string): value is Source {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const source = value as Record<string, unknown>;
  if (source.organization_id !== Number(org) || !positiveId(source.receipt_id)
    || source.entry_id !== Number(entry) || !positiveId(source.version)
    || !source.document || typeof source.document !== "object" || Array.isArray(source.document)) return false;
  const document = source.document as Record<string, unknown>;
  return typeof document.invoice_reference === "string" && typeof document.document_date === "string"
    && typeof document.operation_date === "string" && typeof document.supplier === "string"
    && typeof document.contract === "string" && typeof document.warehouse === "string"
    && typeof document.explanation === "string" && Array.isArray(document.items) && document.items.length > 0
    && document.items.every((value) => {
      if (!value || typeof value !== "object" || Array.isArray(value)) return false;
      const item = value as Record<string, unknown>;
      return typeof item.sku === "string" && typeof item.lot === "string"
        && typeof item.quantity === "string" && typeof item.net_amount === "string"
        && typeof item.vat_amount === "string" && typeof item.vat_rate === "string"
        && typeof item.vat_basis === "string"
        && (item.order_id === undefined || item.order_id === null || positiveId(item.order_id));
    });
}

function readPendingCorrection(org: string, receiptId: number): CorrectionCommand | null {
  const key = correctionJournalKey(org, receiptId);
  const raw = sessionStorage.getItem(key);
  if (raw === null) return null;
  let value: unknown;
  try { value = JSON.parse(raw); }
  catch { throw new Error("Журнал исправления повреждён. Создание нового черновика заблокировано до проверки реестра."); }
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Журнал исправления повреждён. Создание нового черновика заблокировано до проверки реестра.");
  const row = value as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== ["body", "expectedEntryId", "expectedVersion", "key", "org", "originalReceiptId"].sort().join(",")
    || row.org !== org || row.originalReceiptId !== receiptId || !positiveId(row.expectedVersion)
    || !positiveId(row.expectedEntryId) || typeof row.key !== "string" || !uuidPattern.test(row.key))
    throw new Error("Журнал исправления повреждён или относится к другой накладной. Новые отправки заблокированы.");
  const expectedBody = JSON.stringify({ key: row.key, expected_version: row.expectedVersion, expected_entry_id: row.expectedEntryId });
  if (row.body !== expectedBody) throw new Error("Тело сохранённого запроса изменено. Повтор и создание нового черновика заблокированы.");
  return value as CorrectionCommand;
}

function storePendingCorrection(command: CorrectionCommand) {
  const key = correctionJournalKey(command.org, command.originalReceiptId);
  const raw = JSON.stringify(command);
  sessionStorage.setItem(key, raw);
  if (sessionStorage.getItem(key) !== raw) throw new Error("Не удалось надёжно сохранить запрос. Отправка не выполнена.");
}

function clearPendingCorrection(command: CorrectionCommand) {
  const key = correctionJournalKey(command.org, command.originalReceiptId);
  const raw = sessionStorage.getItem(key);
  try {
    if (raw !== null && JSON.stringify(JSON.parse(raw)) === JSON.stringify(command)) sessionStorage.removeItem(key);
  } catch { /* Keep unreadable evidence for explicit recovery. */ }
}

function validCorrectionResponse(value: unknown, command: CorrectionCommand, source: Source): value is CorrectionResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (!positiveId(row.id) || row.id === command.originalReceiptId || row.organization_id !== Number(command.org)
    || row.key !== command.key
    || !positiveId(row.version) || row.status !== "draft" || row.posting !== null
    || !row.correction_of || typeof row.correction_of !== "object" || Array.isArray(row.correction_of)
    || !Array.isArray(row.revisions) || row.revisions.length < 1) return false;
  const relation = row.correction_of as Record<string, unknown>;
  const first = row.revisions[0], latest = row.revisions.at(-1);
  return Object.keys(relation).sort().join(",") === ["entry_id", "receipt_id", "version"].sort().join(",")
    && relation.receipt_id === command.originalReceiptId
    && relation.version === command.expectedVersion
    && relation.entry_id === command.expectedEntryId
    && first && typeof first === "object" && !Array.isArray(first) && first.version === 1
    && latest && typeof latest === "object" && !Array.isArray(latest) && latest.version === row.version
    && canonical(first.document) === canonical(source.document);
}

export function ProcurementPostedReceipt({ org, entry }: { org: string; entry: string }) {
  const key = `${org}/${entry}`;
  const [result, setResult] = useState<{ key: string; source?: Source; error?: string } | null>(null);
  const [correction, setCorrection] = useState<CorrectionState>({ context: "", busy: false, uncertain: false, blocked: false });
  const pendingCorrection = useRef<CorrectionCommand | null>(null);
  const busyCorrection = useRef(false);
  const current = result?.key === key ? result : null;
  const source = current?.source, error = current?.error;
  const sourceReceiptId = source?.receipt_id;
  const correctionView = correction.context === key ? correction : { context: key, busy: false, uncertain: false, blocked: false };

  useEffect(() => {
    let active = true;
    void fetch(`/api/procurement/organizations/${encodeURIComponent(org)}/receipt-postings/${encodeURIComponent(entry)}`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 403 ? "Нет доступа к первичному документу этого юрлица." : response.status === 404 ? "Связанная накладная в выбранном юрлице не найдена." : "Не удалось загрузить первичный документ.");
      return await response.json() as unknown;
    }).then((value) => {
      if (!validSource(value, org, entry)) throw new Error("Сервер вернул накладную или проводку другого юрлица либо неполные исходные данные.");
      if (active) setResult({ key, source: value });
    }).catch((e: Error) => { if (active) setResult({ key, error: e.message }); });
    return () => { active = false; };
  }, [org, entry, key]);

  useEffect(() => {
    if (sourceReceiptId === undefined) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      pendingCorrection.current = null;
      busyCorrection.current = false;
      try {
        const saved = readPendingCorrection(org, sourceReceiptId);
        pendingCorrection.current = saved;
        setCorrection({ context: key, command: saved ?? undefined, busy: false, uncertain: Boolean(saved), blocked: false,
          error: saved ? "Восстановлен неподтверждённый запрос. Повтор использует тот же ключ и те же реквизиты." : undefined });
      } catch (cause) {
        setCorrection({ context: key, busy: false, uncertain: true, blocked: true,
          error: cause instanceof Error ? cause.message : "Не удалось прочитать журнал исправления." });
      }
    });
    return () => { active = false; };
  }, [org, key, sourceReceiptId]);

  async function submitCorrection(command: CorrectionCommand, wasUnknown: boolean) {
    if (busyCorrection.current) return;
    busyCorrection.current = true;
    setCorrection((current) => ({ ...current, context: key, command, busy: true, error: undefined }));
    try {
      const response = await fetch(`/api/procurement/organizations/${encodeURIComponent(command.org)}/receipt-documents/${command.originalReceiptId}/correction-drafts`, {
        method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
        body: command.body,
      });
      let value: unknown;
      try { value = await response.json(); } catch { value = null; }
      if (!response.ok) {
        const detail = value && typeof value === "object" && "detail" in value && typeof value.detail === "string" ? value.detail : "Не удалось создать черновик исправления.";
        throw Object.assign(new Error(detail), { status: response.status });
      }
      if (!source || !validCorrectionResponse(value, command, source)) throw new Error("Ответ сервера не совпадает с юрлицом и исходной накладной. Запрос сохранён для безопасного повтора.");
      clearPendingCorrection(command);
      pendingCorrection.current = null;
      setCorrection({ context: key, busy: false, uncertain: false, blocked: false, created: { id: value.id, version: value.version } });
    } catch (cause) {
      const status = (cause as Error & { status?: number }).status;
      const unknown = status === undefined || status >= 500 || wasUnknown;
      if (unknown) {
        setCorrection({ context: key, command, busy: false, uncertain: true, blocked: false,
          error: `${(cause as Error).message} Результат запроса неизвестен; повторите с тем же ключом.` });
      } else {
        clearPendingCorrection(command);
        pendingCorrection.current = null;
        setCorrection({ context: key, busy: false, uncertain: false, blocked: false, error: (cause as Error).message });
      }
    } finally { busyCorrection.current = false; }
  }

  function createCorrection() {
    if (!source || correctionView.busy || correctionView.uncertain || correctionView.blocked || correctionView.created || pendingCorrection.current) return;
    const correctionKey = crypto.randomUUID();
    const expectedVersion = source.version, expectedEntryId = source.entry_id;
    const command: CorrectionCommand = { org, originalReceiptId: source.receipt_id, expectedVersion,
      expectedEntryId, key: correctionKey, body: JSON.stringify({ key: correctionKey,
        expected_version: expectedVersion, expected_entry_id: expectedEntryId }) };
    try { storePendingCorrection(command); }
    catch (cause) {
      setCorrection({ context: key, busy: false, uncertain: false, blocked: true,
        error: cause instanceof Error ? cause.message : "Не удалось сохранить запрос исправления." });
      return;
    }
    pendingCorrection.current = command;
    void submitCorrection(command, false);
  }

  function retryCorrection() {
    const command = pendingCorrection.current;
    if (!command || correctionView.busy || correctionView.blocked) return;
    void submitCorrection(command, correctionView.uncertain);
  }

  return <main className="w-full space-y-4 overflow-auto p-6 lg:pr-24"><h1 className="text-2xl font-semibold">Проведённая первичная накладная</h1>
    {error && <p role="alert">{error}</p>}{!source && !error && <p role="status">Загрузка первичного документа…</p>}
    {source && <section className="space-y-3 rounded-xl border border-line bg-surface p-5"><h2 className="font-semibold">{source.document.invoice_reference} · версия {source.version}</h2><p>Юрлицо № {source.organization_id} · накладная № {source.receipt_id} · проводка № {source.entry_id}</p><p>Сохранённая версия, на основании которой выполнено проведение.</p><dl className="grid gap-3 md:grid-cols-2">{[["Дата документа", source.document.document_date], ["Дата операции", source.document.operation_date], ["Поставщик", source.document.supplier], ["Поставщик: справочник", source.document.supplier_id ? `ID ${source.document.supplier_id} · УНП ${source.document.supplier_unp || "не указан"}` : "Связь исторического документа неизвестна"], ["Договор", source.document.contract], ["Склад", source.document.warehouse], ["Содержание", source.document.explanation]].map(([label, value]) => <div key={label}><dt className="text-sm text-muted">{label}</dt><dd>{value}</dd></div>)}</dl><div className="overflow-auto"><table className="w-full text-left text-sm"><caption className="py-3 text-left">Строки накладной · суммы в BYN</caption><thead><tr>{["Номенклатура / партия", "Количество", "Без НДС", "НДС", "Ставка / основание", "Заказ"].map((label) => <th className="p-2" key={label}>{label}</th>)}</tr></thead><tbody>{source.document.items.map((item, i) => <tr key={i} className="border-t border-line"><td className="p-2">{item.sku} · {item.lot}</td><td>{item.quantity}</td><td>{item.net_amount}</td><td>{item.vat_amount}</td><td>{item.vat_rate}% · {item.vat_basis}</td><td>{item.order_id ?? "—"}</td></tr>)}</tbody></table></div></section>}
    {source && <section className="space-y-2 rounded-xl border border-line bg-surface p-4">
      <h2 className="font-semibold">Исправление первичной накладной</h2>
      <p>Будет создан отдельный связанный черновик. Исходная накладная и проводка № {source.entry_id} останутся без изменений.</p>
      <p>Этот черновик пока нельзя провести или передать в WMS. Для него нужен отдельный workflow исправлений.</p>
      {correctionView.error && <p role="alert">{correctionView.error}</p>}
      {correctionView.busy && <p role="status">Создаём черновик исправления…</p>}
      {correctionView.uncertain && !correctionView.blocked && correctionView.command && <button type="button" disabled={correctionView.busy} onClick={retryCorrection} className="rounded border border-line px-3 py-2">Повторить тот же запрос</button>}
      {correctionView.created && <p role="status">Черновик исправления № {correctionView.created.id}, версия {correctionView.created.version}, создан.</p>}
      {!correctionView.created && !correctionView.command && !correctionView.blocked && <button type="button" disabled={correctionView.busy} onClick={createCorrection} className="rounded border border-line px-3 py-2">Создать черновик исправления</button>}
      {correctionView.created && <Link className="block text-accent underline" href={`/erp/procurement/receipts?org=${encodeURIComponent(org)}&receipt=${correctionView.created.id}`}>Открыть черновик исправления в реестре накладных</Link>}
    </section>}
    {source && <Link className="block text-accent underline" href={`/erp/wms/receipts/from-primary?org=${source.organization_id}&receipt=${source.receipt_id}&version=${source.version}`}>Подготовить складскую приёмку по исходной накладной</Link>}
    <Link className="text-accent underline" href={`/erp/procurement/receipts?org=${encodeURIComponent(org)}`}>Все накладные на поступление</Link>
  </main>;
}
