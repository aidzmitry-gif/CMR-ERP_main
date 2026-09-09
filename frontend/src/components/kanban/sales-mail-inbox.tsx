"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { createDeal, type DealInput } from "@/lib/api";
import {
  assignInboxEmail,
  fetchInboxDetail,
  fetchInboxPage,
  fetchSalesDeals,
  inboxAttachmentUrl,
  type IncomingEmail,
  type IncomingEmailDetail,
  type SalesDealOption,
  SalesMailHttpError,
} from "@/lib/sales-mail-api";
import { SALES_STAGES } from "@/lib/sales-stages";
import type { Stage } from "@/lib/types";

type LoadState = "loading" | "error" | "ready";

const modalStages: Stage[] = SALES_STAGES.map((stage) => ({
  ...stage,
  count: 0,
  sum: 0,
  deals: [],
}));

const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString("ru-RU") : "—";

function attachmentSize(size: number | null) {
  return size == null ? "размер не указан" : `${Math.ceil(size / 1024)} КБ`;
}

function strictDealId(value: string | number) {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(numeric) && numeric > 0 ? numeric : null;
}

export function SalesMailInbox({ canAssignOwner = false }: { canAssignOwner?: boolean }) {
  const [state, setState] = useState<LoadState>("loading");
  const [items, setItems] = useState<IncomingEmail[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [selected, setSelected] = useState<IncomingEmailDetail | null>(null);
  const [dealOptions, setDealOptions] = useState<SalesDealOption[]>([]);
  const [dealSearch, setDealSearch] = useState("");
  const [selectedDealId, setSelectedDealId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [createdDealIds, setCreatedDealIds] = useState<Record<string, string>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const detailGeneration = useRef(0);
  const loadGeneration = useRef(0);
  const live = useRef(true);

  const selectedReceiptId = selected?.receipt_id ?? null;
  const createdDealId = selectedReceiptId ? createdDealIds[selectedReceiptId] ?? null : null;
  const visibleDeals = useMemo(() => {
    const query = dealSearch.trim().toLocaleLowerCase();
    if (!query) return dealOptions.slice(0, 50);
    return dealOptions.filter((deal) => [deal.number, deal.counterparty, deal.title]
      .some((field) => field.toLocaleLowerCase().includes(query))).slice(0, 50);
  }, [dealOptions, dealSearch]);

  async function loadInbox(offset = 0) {
    const generation = ++loadGeneration.current;
    try {
      const page = await fetchInboxPage(offset);
      if (!live.current || generation !== loadGeneration.current) return;
      setItems(offset === 0 ? page.items : (current) => [...current, ...page.items]);
      setNextOffset(page.next_offset);
      setState("ready");
    } catch (reason) {
      if (!live.current || generation !== loadGeneration.current) return;
      setState("error");
      setError(reason instanceof SalesMailHttpError && reason.status === 403
        ? "У вас нет доступа к разбору почты отдела продаж."
        : reason instanceof Error ? reason.message : "Очередь входящих временно недоступна.");
    }
  }

  async function loadInitial() {
    const generation = ++loadGeneration.current;
    try {
      const [page, deals] = await Promise.all([fetchInboxPage(), fetchSalesDeals()]);
      if (!live.current || generation !== loadGeneration.current) return;
      setItems(page.items);
      setNextOffset(page.next_offset);
      setDealOptions(deals);
      setState("ready");
      setError(null);
    } catch (reason) {
      if (!live.current || generation !== loadGeneration.current) return;
      setState("error");
      setError(reason instanceof SalesMailHttpError && reason.status === 403
        ? "У вас нет доступа к разбору почты отдела продаж."
        : reason instanceof Error ? reason.message : "Очередь входящих временно недоступна.");
    }
  }

  function reload() {
    setState("loading");
    setError(null);
    void loadInitial();
  }

  useEffect(() => {
    live.current = true;
    void Promise.resolve().then(() => loadInitial());
    return () => { live.current = false; };
  }, []);

  async function openItem(item: IncomingEmail) {
    const generation = ++detailGeneration.current;
    setError(null);
    setSelected(null);
    setDealSearch("");
    setSelectedDealId("");
    try {
      const detail = await fetchInboxDetail(item.receipt_id);
      if (live.current && generation === detailGeneration.current) setSelected(detail);
    } catch (reason) {
      if (live.current && generation === detailGeneration.current) {
        setError(reason instanceof Error ? reason.message : "Не удалось открыть письмо.");
      }
    }
  }

  async function assign(receiptId: string, dealId: number): Promise<boolean> {
    if (!strictDealId(dealId)) {
      setError("Выберите существующую сделку из списка.");
      return false;
    }
    setAssigning(true);
    setError(null);
    try {
      await assignInboxEmail(receiptId, dealId);
      if (!live.current) return true;
      setCreatedDealIds((current) => {
        const next = { ...current };
        delete next[receiptId];
        return next;
      });
      if (selectedReceiptId === receiptId) {
        setSelected(null);
        setSelectedDealId("");
      }
      await loadInbox();
      return true;
    } catch (reason) {
      if (live.current) setError(reason instanceof Error ? reason.message : "Не удалось назначить письмо. ID созданной сделки сохранён для повтора.");
      return false;
    } finally {
      if (live.current) setAssigning(false);
    }
  }

  function assignSelected() {
    if (!selectedReceiptId) return;
    const dealId = strictDealId(selectedDealId);
    if (dealId == null || !dealOptions.some((deal) => deal.id === dealId)) {
      setError("Выберите существующую сделку из списка.");
      return;
    }
    void assign(selectedReceiptId, dealId);
  }

  async function createAndAssign(input: DealInput) {
    const receiptId = selectedReceiptId;
    if (!receiptId) return false;
    const knownId = createdDealIds[receiptId];
    if (knownId) {
      const dealId = strictDealId(knownId);
      if (dealId == null) {
        setError("ID созданной сделки нельзя безопасно использовать для повтора.");
        return false;
      }
      setCreateOpen(false);
      return assign(receiptId, dealId);
    }
    setAssigning(true);
    setError(null);
    try {
      const created = await createDeal(input);
      if (!created) return false;
      const dealId = strictDealId(created.id);
      setCreatedDealIds((current) => ({ ...current, [receiptId]: created.id }));
      setCreateOpen(false);
      if (dealId != null) return await assign(receiptId, dealId);
      if (live.current) setError("CRM вернула некорректный ID созданной сделки.");
      return false;
    } catch (reason) {
      if (live.current) setError(reason instanceof Error ? reason.message : "Не удалось создать сделку.");
      return false;
    } finally {
      if (live.current) setAssigning(false);
    }
  }

  const selectedItem = selected ? items.find((item) => item.receipt_id === selected.receipt_id) : null;

  return <main className="flex-1 overflow-auto bg-canvas p-6 text-ink">
    <div className="mx-auto max-w-[1100px] space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Почта отдела продаж</h1>
          <p className="mt-1 text-sm text-muted">Разбор входящих order@microchips.by. Назначение письма сохраняется отдельным действием.</p>
        </div>
        <Button variant="secondary" size="sm" disabled={state === "loading" || assigning} onClick={reload}>Обновить</Button>
      </div>

      {error && <p role="alert" className="rounded border border-line bg-surface p-3 text-sm text-danger">{error}</p>}
      {state === "loading" && <p role="status" className="rounded border border-line bg-surface p-6 text-center text-sm text-muted">Загрузка очереди…</p>}
      {state === "error" && !items.length && <p role="status" className="rounded border border-line bg-surface p-6 text-center text-sm text-muted">Очередь входящих недоступна.</p>}
      {state === "ready" && !items.length && <p role="status" className="rounded border border-line bg-surface p-6 text-center text-sm text-muted">В очереди нет неразобранных писем.</p>}

      {items.length > 0 && <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section aria-label="Очередь входящих писем" className="space-y-2">
          {items.map((item) => <button key={item.receipt_id} type="button" disabled={assigning} onClick={() => void openItem(item)}
            className={`w-full rounded border bg-surface p-3 text-left shadow-card ${selected?.receipt_id === item.receipt_id ? "border-accent" : "border-line"}`}>
            <span className="block font-semibold">{item.subject || "Без темы"}</span>
            <span className="mt-1 block text-xs text-muted">{date(item.message_date ?? item.received_at)} · {item.sender ?? "отправитель не указан"}</span>
            <span className="mt-1 block text-xs text-muted">{item.owner ?? "Не назначено"} · вложений: {item.attachments.length}</span>
          </button>)}
          {nextOffset != null && <Button variant="secondary" size="sm" disabled={assigning} onClick={() => void loadInbox(nextOffset)}>Загрузить ещё</Button>}
        </section>

        <section aria-label="Детали входящего письма" className="rounded border border-line bg-surface p-4 shadow-card">
          {!selected && <p className="text-sm text-muted">Выберите письмо, чтобы прочитать его и назначить сделку.</p>}
          {selected && <div className="space-y-3">
            <div><h2 className="font-semibold">{selected.subject || "Без темы"}</h2><p className="text-xs text-muted">От: {selected.sender ?? "не указан"} · {date(selected.message_date ?? selected.received_at)}</p><p className="text-xs text-muted">Ответственный: {selected.owner ?? "не назначен"}</p></div>
            <p className="whitespace-pre-wrap rounded bg-sunken p-3 text-sm">{selected.body_text || "(пустой текст)"}</p>
            {selected.attachments.length > 0 && <div className="space-y-1">
              <p className="text-xs font-semibold text-muted">Вложения</p>
              {selected.attachments.map((file) => <div key={`${file.filename}-${file.index}`} className="text-xs">
                {file.downloadable ? <a href={inboxAttachmentUrl(selected.receipt_id, file.index)} target="_blank" rel="noreferrer" className="text-accent-ink underline">{file.filename} · {attachmentSize(file.size)}</a> : <span>{file.filename} · скачивание заблокировано: {file.blocked_reason ?? "причина не указана"}{file.size != null ? ` · ${attachmentSize(file.size)}` : ""}</span>}
              </div>)}
            </div>}
            <div className="space-y-2 border-t border-line pt-3">
              <p className="text-sm font-semibold">Назначить существующую сделку</p>
              <label className="block text-xs text-muted">Поиск по номеру, компании или названию
                <input aria-label="Поиск сделки" value={dealSearch} disabled={assigning} onChange={(event) => { setDealSearch(event.target.value); setSelectedDealId(""); }} className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm" placeholder="например, CRM-42" />
              </label>
              <div className="flex gap-2"><select aria-label="Существующая сделка" value={selectedDealId} disabled={assigning} onChange={(event) => setSelectedDealId(event.target.value)} className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1.5 text-sm">
                <option value="">Выберите сделку</option>
                {visibleDeals.map((deal) => <option key={deal.id} value={deal.id}>{deal.number} · {deal.counterparty} · {deal.title}</option>)}
              </select>
                <Button size="sm" disabled={assigning || !selectedDealId} onClick={assignSelected}>Назначить</Button></div>
              {dealOptions.length === 0 && <p className="text-xs text-muted">Нет доступных сделок для назначения.</p>}
              <Button variant="secondary" size="sm" disabled={assigning || !!createdDealId} onClick={() => setCreateOpen(true)}>Создать новую сделку и назначить</Button>
              {createdDealId && <div className="rounded border border-line bg-sunken p-2 text-xs">
                <p>Сделка создана, ID сохранён: <strong>{createdDealId}</strong>.</p>
                <p className="mt-1 text-muted">Если назначение не прошло, повторите его с этим ID — новая сделка создаваться не будет.</p>
                <Button size="sm" className="mt-2" disabled={assigning} onClick={() => {
                  const dealId = strictDealId(createdDealId);
                  if (dealId == null) setError("ID созданной сделки нельзя безопасно использовать для повтора.");
                  else void assign(selected.receipt_id, dealId);
                }}>Повторить назначение</Button>
              </div>}
            </div>
          </div>}
        </section>
      </div>}
    </div>
    {createOpen && selectedItem && <CreateDealModal
      stages={modalStages}
      defaultStage="new"
      onClose={() => setCreateOpen(false)}
      onCreate={createAndAssign}
      canAssignOwner={canAssignOwner}
    />}
  </main>;
}
