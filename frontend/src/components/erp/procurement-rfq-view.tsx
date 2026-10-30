"use client";

import { useInstanceOrganization,withInstanceOrganization } from "@/components/instance-organization-gate";

import clsx from "clsx";
import { Award,Plus,RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect,useMemo,useRef,useState } from "react";

import { formatNumber } from "@/lib/format";
import {
addBid,
awardRfq,
createRfq,
fetchRfqs,
type Rfq,
statusLabel,
} from "@/lib/procurement-rfq";

type Organization = { id: number; name: string; unp: string };
type RequestOption = { id: number; number: string; item: string };
type SupplierOption = { id: number; name: string; unp: string };
type HistoryItem = { id: number; action: "create" | "bid" | "award"; actor: string;
  created_at: string; before: Record<string, unknown> | null; after: Record<string, unknown> };
type CreateJournal = { kind: "create"; org: number; requestId: number; key: string };
type BidJournal = { kind: "bid"; org: number; rfqId: number; key: string;
  bid: { supplier_id: number; price_byn: string; lead_time_days: number | null; incoterms: string } };
type Journal = CreateJournal | BidJournal;
const journalKey = "procurement-rfq:pending:v1";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const positive = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;

function pendingJournal(): Journal | null {
  const raw = sessionStorage.getItem(journalKey);
  if (raw === null) return null;
  const value = JSON.parse(raw) as Journal;
  if (!value || !positive(value.org) || !uuid.test(value.key) ||
      (value.kind === "create" ? !positive(value.requestId) :
        value.kind !== "bid" || !positive(value.rfqId) || !value.bid ||
        !positive(value.bid.supplier_id) || typeof value.bid.price_byn !== "string" ||
        typeof value.bid.incoterms !== "string")) throw new Error("Журнал RFQ повреждён. Новая отправка запрещена.");
  return value;
}

function holdJournal(value: Journal) {
  const current = pendingJournal();
  if (current && JSON.stringify(current) !== JSON.stringify(value))
    throw new Error("Сначала завершите неопределённую отправку RFQ.");
  sessionStorage.setItem(journalKey, JSON.stringify(value));
  if (JSON.stringify(pendingJournal()) !== JSON.stringify(value))
    throw new Error("Журнал RFQ не подтверждён. Отправка запрещена.");
}

function clearJournal(value: Journal) {
  if (JSON.stringify(pendingJournal()) !== JSON.stringify(value))
    throw new Error("Журнал RFQ изменился; проверьте результат перед новой отправкой.");
  sessionStorage.removeItem(journalKey);
}

async function read<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Ошибка ${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

const STATUS_TONE: Record<string, string> = {
  open: "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  awarded: "bg-green-50 text-green-700 dark:bg-green-500/10 dark:text-green-300",
  cancelled: "bg-sunken text-muted",
};

 function ProcurementRfqViewWorkspace() {
  const [, setOrganizations] = useState<Organization[]>([]);
  const org = String(useInstanceOrganization().id);
  const [requests, setRequests] = useState<RequestOption[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]);
  const [rfqs, setRfqs] = useState<Rfq[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [uncertainCreate, setUncertainCreate] = useState(false);
  const [uncertainBid, setUncertainBid] = useState(false);
  const [journalBlocked, setJournalBlocked] = useState(false);
  const [pendingBidTarget, setPendingBidTarget] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [requestId, setRequestId] = useState("");
  const [requestSearch, setRequestSearch] = useState("");
  const [supplierSearch, setSupplierSearch] = useState("");
  const [bid, setBid] = useState({ supplier_id: "", price_byn: "", lead_time_days: "", incoterms: "" });
  const pendingCreate = useRef<string | null>(null);
  const pendingBid = useRef<string | null>(null);

  useEffect(() => {
    let live = true;
    void read<Organization[]>("/api/procurement/receipt-organizations")
      .then((rows) => {
        if (!live) return;
        setOrganizations(rows);
        const pending = pendingJournal();
        if (!pending) return;
        if (pending.org !== Number(org) || !rows.some((row) => row.id === pending.org))
          throw new Error("Юрлицо незавершённого RFQ недоступно. Новая отправка запрещена.");

        if (pending.kind === "create") {
          pendingCreate.current = pending.key;
          setRequestId(String(pending.requestId)); setUncertainCreate(true);
        } else {
          pendingBid.current = pending.key;
          setPendingBidTarget(pending.rfqId);
          setBid({ supplier_id: String(pending.bid.supplier_id), price_byn: pending.bid.price_byn,
            lead_time_days: pending.bid.lead_time_days === null ? "" : String(pending.bid.lead_time_days),
            incoterms: pending.bid.incoterms });
          setUncertainBid(true);
        }
      })
      .catch((cause) => { if (live) { setError(String(cause)); setJournalBlocked(true); } });
    return () => { live = false; };
  }, [org]);

  useEffect(() => {
    if (!org) return;
    let live = true;
    const id = Number(org);
    void Promise.all([
      read<{ organization_id: number; items: RequestOption[] }>(`/api/procurement/organizations/${id}/owned-sources?kind=request`),
      read<{ organization_id: number; items: SupplierOption[] }>(`/api/procurement/organizations/${id}/supplier-options`),
      fetchRfqs(id),
    ]).then(async ([requestPage, supplierPage, rfqPage]) => {
      if (!live) return;
      if (requestPage.organization_id !== id || supplierPage.organization_id !== id || !rfqPage) throw new Error("ERP не подтвердила данные выбранного юрлица");
      let items = rfqPage.items;
      if (pendingBidTarget && !items.some((row) => row.id === pendingBidTarget)) {
        const target = await read<Rfq>(`/api/procurement/organizations/${id}/rfq/${pendingBidTarget}`);
        if (target.organization_id !== id || target.id !== pendingBidTarget) throw new Error("ERP не подтвердила незавершённый RFQ");
        items = [target, ...items];
      }
      if (!live) return;
      setRequests(requestPage.items);
      setSuppliers(supplierPage.items);
      setRfqs(items);
      setNext(rfqPage.next_after_id);
      setSelId(pendingBidTarget ?? items[0]?.id ?? null);
    }).catch((cause) => { if (live) setError(String(cause)); });
    return () => { live = false; };
  }, [org, pendingBidTarget]);

  useEffect(() => {
    if (!org || !selId) return;
    let live = true;
    void read<{ organization_id: number; rfq_id: number; items: HistoryItem[] }>(
      `/api/procurement/organizations/${org}/rfq/${selId}/history`)
      .then((page) => {
        if (!live) return;
        if (page.organization_id !== Number(org) || page.rfq_id !== selId || !Array.isArray(page.items))
          throw new Error("ERP не подтвердила историю выбранного RFQ");
        setHistory(page.items);
        setHistoryLoaded(true);
      })
      .catch((cause) => { if (live) setHistoryError(String(cause)); });
    return () => { live = false; };
  }, [org, selId, historyRevision]);

  const selected = useMemo(() => rfqs.find((r) => r.id === selId) ?? null, [rfqs, selId]);

  async function refresh(keep?: number) {
    if (!org) return;
    const page = await fetchRfqs(Number(org));
    if (!page) { setError("Не удалось обновить RFQ выбранного юрлица"); return; }
    setRfqs(page.items); setNext(page.next_after_id);
    setSelId(keep ?? page.items[0]?.id ?? null);
    setHistory([]); setHistoryError(""); setHistoryLoaded(false);
    setHistoryRevision((current) => current + 1);
  }

  async function searchOptions(kind: "request" | "supplier") {
    if (!org) return;
    setError("");
    try {
      if (kind === "request") {
        const page = await read<{ organization_id: number; items: RequestOption[] }>(
          `/api/procurement/organizations/${org}/owned-sources?kind=request&q=${encodeURIComponent(requestSearch)}`);
        if (page.organization_id !== Number(org)) throw new Error("Неверное юрлицо в ответе заявок");
        setRequests(page.items);
        setRequestId("");
      } else {
        const page = await read<{ organization_id: number; items: SupplierOption[] }>(
          `/api/procurement/organizations/${org}/supplier-options?q=${encodeURIComponent(supplierSearch)}`);
        if (page.organization_id !== Number(org)) throw new Error("Неверное юрлицо в ответе поставщиков");
        setSuppliers(page.items);
        setBid((current) => ({ ...current, supplier_id: "" }));
      }
    } catch (cause) { setError(String(cause)); }
  }

  async function onCreate() {
    if (journalBlocked || !org || !requestId) {
      setError("Выберите юрлицо и заявку на закупку");
      return;
    }
    const key = pendingCreate.current ?? crypto.randomUUID();
    const journal: CreateJournal = { kind: "create", org: Number(org), requestId: Number(requestId), key };
    try { holdJournal(journal); }
    catch (cause) { setError(String(cause)); return; }
    pendingCreate.current = key;
    setBusy(true);
    setError("");
    const created = await createRfq(Number(org), { request_key: key, request_id: Number(requestId) });
    setBusy(false);
    if (!created) {
      setUncertainCreate(true);
      setError("Исход создания не подтверждён. Повтор использует тот же ключ — проверьте список RFQ.");
      return;
    }
    try { clearJournal(journal); }
    catch (cause) { setUncertainCreate(true); setError(String(cause)); return; }
    pendingCreate.current = null;
    setUncertainCreate(false);
    setRequestId("");
    await refresh(created.id);
  }

  async function onAddBid() {
    if (journalBlocked || !org || !selected || !bid.supplier_id || !/^\d+(?:\.\d{1,2})?$/.test(bid.price_byn)) {
      setError("Выберите поставщика из справочника и укажите цену в BYN");
      return;
    }
    const key = pendingBid.current ?? crypto.randomUUID();
    const bidBody = { supplier_id: Number(bid.supplier_id), price_byn: bid.price_byn,
      lead_time_days: bid.lead_time_days ? Number(bid.lead_time_days) : null, incoterms: bid.incoterms };
    const journal: BidJournal = { kind: "bid", org: Number(org), rfqId: selected.id, key, bid: bidBody };
    try { holdJournal(journal); }
    catch (cause) { setError(String(cause)); return; }
    pendingBid.current = key;
    setBusy(true);
    setError("");
    const updated = await addBid(Number(org), selected.id, { bid_key: key, ...bidBody });
    setBusy(false);
    if (!updated) {
      setUncertainBid(true);
      setError("Исход предложения не подтверждён. Повтор использует тот же ключ.");
      return;
    }
    try { clearJournal(journal); }
    catch (cause) { setUncertainBid(true); setError(String(cause)); return; }
    pendingBid.current = null;
    setUncertainBid(false);
    setPendingBidTarget(null);
    setBid({ supplier_id: "", price_byn: "", lead_time_days: "", incoterms: "" });
    await refresh(selected.id);
  }

  async function onAward(bidId: number) {
    if (!selected || !org || journalBlocked || uncertainCreate || uncertainBid) return;
    setBusy(true);
    setError("");
    const updated = await awardRfq(Number(org), selected.id, bidId);
    setBusy(false);
    if (!updated) {
      setError("Не удалось выбрать победителя");
      return;
    }
    await refresh(selected.id);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Тендер выбранного юрлица: заявка → запрос цен → предложения поставщиков → победитель.
        </p>
        <button
          onClick={() => void refresh(selId ?? undefined)}
          disabled={busy || !org}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
        >
          <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
        </button>
      </div>

      <span className="text-sm text-muted">Юрлицо задано в настройках.</span>

      {error && <div className="mt-3 text-sm text-red-600">{error}</div>}

      {!org && <p className="mt-5 text-sm text-muted">Выберите юрлицо, чтобы открыть его запросы цен.</p>}
      {org && <>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        {/* Список RFQ */}
        <div>
          <div className="mb-2 flex gap-2">
            <input aria-label="Поиск заявки" value={requestSearch} onChange={(event) => setRequestSearch(event.target.value)}
              disabled={busy || uncertainCreate || journalBlocked} placeholder="Найти заявку"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink" />
            <button type="button" onClick={() => void searchOptions("request")}
              disabled={busy || uncertainCreate || journalBlocked} className="rounded-lg border border-line px-2 text-sm">Найти</button>
          </div>
          <div className="mb-2 flex gap-2">
            <select aria-label="Заявка на закупку" value={requestId} disabled={busy || uncertainCreate || uncertainBid || journalBlocked}
              onChange={(e) => setRequestId(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink">
              <option value="">Заявка на закупку</option>
              {requestId && !requests.some((row) => String(row.id) === requestId) &&
                <option value={requestId}>Заявка #{requestId} · незавершённая отправка</option>}
              {requests.map((row) => <option key={row.id} value={row.id}>{row.number} · {row.item}</option>)}
            </select>
            <button
              onClick={onCreate}
              disabled={busy || !requestId || uncertainBid || journalBlocked}
              aria-label="Создать RFQ"
              className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
            >
              <Plus size={15} />
            </button>
          </div>
          <div className="overflow-hidden rounded-xl border border-line bg-surface">
            {rfqs.length === 0 && <div className="px-4 py-6 text-center text-sm text-muted">Запросов нет</div>}
            {rfqs.map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  setSelId(r.id); setHistory([]); setHistoryError(""); setHistoryLoaded(false);
                }}
                disabled={busy || uncertainBid}
                className={clsx(
                  "flex w-full items-center justify-between border-b border-line px-4 py-2.5 text-left last:border-0 hover:bg-sunken/50",
                  selId === r.id && "bg-sunken/60",
                )}
              >
                <span className="truncate text-sm text-ink">{r.number} · {r.item}</span>
                <span className="ml-2 shrink-0 text-[11px] text-faint">{r.bids.length} пред.</span>
              </button>
            ))}
            {next !== null && <button className="w-full px-4 py-2 text-sm text-accent" disabled={busy}
              onClick={async () => {
                const page = await fetchRfqs(Number(org), next);
                if (!page) { setError("Не удалось загрузить следующую страницу RFQ"); return; }
                setRfqs((current) => [...current, ...page.items]); setNext(page.next_after_id);
              }}>Показать ещё</button>}
          </div>
        </div>

        {/* Карточка RFQ с предложениями */}
        <div>
          {!selected ? (
            <div className="rounded-xl border border-line bg-surface px-4 py-10 text-center text-muted">
              Выберите запрос слева
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <div>
                  <div className="font-semibold text-ink">{selected.number} · {selected.item}</div>
                  <div className="text-[11px] text-faint">
                    {selected.sku_code && `${selected.sku_code} · `}
                    {formatNumber(selected.qty)} шт
                  </div>
                </div>
                <span
                  className={clsx(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    STATUS_TONE[selected.status] ?? "bg-sunken text-muted",
                  )}
                >
                  {statusLabel(selected.status)}
                </span>
              </div>

              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th className="px-4 py-2 font-medium">Поставщик</th>
                    <th className="px-4 py-2 text-right font-medium">Цена, BYN</th>
                    <th className="px-4 py-2 text-right font-medium">Срок, дн</th>
                    <th className="px-4 py-2 font-medium">Incoterms</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {selected.bids.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-5 text-center text-muted">
                        Предложений пока нет
                      </td>
                    </tr>
                  )}
                  {selected.bids.map((b) => {
                    const isBest = b.id === selected.best_bid_id;
                    return (
                      <tr
                        key={b.id}
                        className={clsx(
                          "border-b border-line last:border-0",
                          b.is_winner && "bg-green-50/50 dark:bg-green-500/5",
                        )}
                      >
                        <td className="px-4 py-2.5 text-muted">
                          {suppliers.find((supplier) => supplier.id === b.supplier_id)?.name ?? (b.supplier_id ? `#${b.supplier_id}` : "—")}
                          {b.is_winner && <span className="ml-1.5 text-[11px] font-semibold text-green-600">победитель</span>}
                        </td>
                        <td
                          className={clsx(
                            "px-4 py-2.5 text-right font-semibold tabular-nums",
                            isBest ? "text-green-600" : "text-ink",
                          )}
                        >
                          {formatNumber(b.price_byn)}
                          {isBest && <span className="ml-1 text-[10px] text-green-600">лучшая</span>}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-muted">{b.lead_time_days ?? "—"}</td>
                        <td className="px-4 py-2.5 text-muted">{b.incoterms || "—"}</td>
                        <td className="px-4 py-2.5 text-right">
                          {selected.status === "open" && (
                            <button
                              onClick={() => onAward(b.id)}
                              disabled={busy || uncertainCreate || uncertainBid || journalBlocked}
                              className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:bg-sunken disabled:opacity-50"
                            >
                              <Award size={13} /> Выбрать
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {selected.status === "awarded" && (
                <div className="border-t border-line p-4 text-sm text-muted">
                  Победитель выбран. Создайте заказ в этом юрлице и подтвердите поставщика в справочнике.{" "}
                  <Link className="text-accent underline" href="/erp/procurement/orders">Создать заказ поставщику</Link>
                </div>
              )}

              {selected.status === "open" && (
                <div className="border-t border-line p-4">
                  <div className="mb-2 flex gap-2"><input aria-label="Поиск поставщика" value={supplierSearch}
                    onChange={(event) => setSupplierSearch(event.target.value)}
                    disabled={busy || uncertainBid || journalBlocked} placeholder="Найти поставщика"
                    className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink" />
                    <button type="button" onClick={() => void searchOptions("supplier")}
                      disabled={busy || uncertainBid || journalBlocked}
                      className="rounded-lg border border-line px-2 text-sm">Найти поставщика</button></div>
                  <div className="flex flex-wrap items-end gap-2">
                  <select aria-label="Поставщик предложения" value={bid.supplier_id}
                    disabled={busy || uncertainBid}
                    onChange={(e) => setBid({ ...bid, supplier_id: e.target.value })}
                    className="w-48 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink">
                    <option value="">Поставщик из справочника</option>
                    {bid.supplier_id && !suppliers.some((row) => String(row.id) === bid.supplier_id) &&
                      <option value={bid.supplier_id}>Поставщик #{bid.supplier_id} · незавершённая отправка</option>}
                    {suppliers.map((row) => <option key={row.id} value={row.id}>{row.name} · {row.unp}</option>)}
                  </select>
                  <input
                    value={bid.price_byn}
                    onChange={(e) => setBid({ ...bid, price_byn: e.target.value })}
                    placeholder="Цена, BYN"
                    inputMode="decimal"
                    disabled={busy || uncertainBid}
                    className="w-32 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={bid.lead_time_days}
                    onChange={(e) => setBid({ ...bid, lead_time_days: e.target.value })}
                    placeholder="Срок, дн"
                    type="number"
                    disabled={busy || uncertainBid}
                    className="w-24 rounded-lg border border-line bg-surface px-3 py-2 text-right text-sm tabular-nums text-ink outline-none focus:border-accent"
                  />
                  <input
                    value={bid.incoterms}
                    onChange={(e) => setBid({ ...bid, incoterms: e.target.value })}
                    placeholder="Incoterms"
                    disabled={busy || uncertainBid}
                    className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                  />
                  <button
                    onClick={onAddBid}
                    disabled={busy || !bid.supplier_id || !bid.price_byn || uncertainCreate || journalBlocked}
                    className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
                  >
                    <Plus size={15} /> Предложение
                  </button>
                  </div>
                </div>
              )}
              <div className="border-t border-line p-4 text-sm">
                <h3 className="font-semibold text-ink">История RFQ</h3>
                {historyError && <p className="mt-2 text-red-600">История недоступна: {historyError}</p>}
                {!historyError && history.length === 0 && <p className="mt-2 text-muted">{historyLoaded ? "Записей истории нет" : "История загружается"}</p>}
                {history.map((entry) => <div key={entry.id} className="mt-2 rounded-lg border border-line p-2">
                  <p className="font-medium text-ink">{entry.action === "create" ? "Создан запрос" : entry.action === "bid" ? "Добавлено предложение" : "Выбран победитель"}</p>
                  <p className="text-muted">{entry.actor} · {new Date(entry.created_at).toLocaleString("ru-BY")}</p>
                  {entry.action === "create" && <p>Заявка #{String(entry.after.request_id)} · {String(entry.after.item)} · {String(entry.after.quantity)} шт</p>}
                  {entry.action === "bid" && <p>Предложение #{String(entry.after.bid_id)} · поставщик #{String(entry.after.supplier_id)} · {String(entry.after.price_byn)} BYN</p>}
                  {entry.action === "award" && <p>Открыт → победитель: предложение #{String(entry.after.winner_bid_id)}</p>}
                </div>)}
              </div>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  );
}

export const ProcurementRfqView = withInstanceOrganization(ProcurementRfqViewWorkspace);
