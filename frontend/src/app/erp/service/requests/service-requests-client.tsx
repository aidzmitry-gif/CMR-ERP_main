"use client";

import { DndContext, PointerSensor, useDraggable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { Plus, RefreshCw, Search, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { FunnelCardView, FunnelColumn } from "@/components/funnel/funnel-board";
import {
  createServiceRequest, loadServiceRequests, SERVICE_PRIORITIES, SERVICE_STATUSES,
  serviceCard, ServiceRequestError, serviceStages, updateServiceRequest,
  type ServiceRequestDraft, type ServiceRequestRow,
} from "@/lib/service-requests";

const blank = (): ServiceRequestDraft => ({ title: "", description: "", priority: "normal" });
const button = "inline-flex items-center justify-center gap-2 rounded-lg border border-line bg-surface px-4 py-2 text-sm font-medium text-ink disabled:opacity-50";
const input = "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

function RequestCard({ row, blocked, onOpen }: { row: ServiceRequestRow; blocked: boolean; onOpen: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: row.id, disabled: blocked });
  return <button ref={setNodeRef} {...attributes} {...listeners} type="button" disabled={blocked}
    aria-label={`Открыть заявку SR-${row.id}: ${row.title}`} onClick={onOpen}
    className={`w-full text-left focus-visible:rounded-xl focus-visible:outline-accent ${isDragging ? "opacity-40" : ""}`}>
    <FunnelCardView card={serviceCard(row)} />
  </button>;
}

export function ServiceRequestsClient() {
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState<{ revision: number; rows?: ServiceRequestRow[]; error?: "auth" | "read" } | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [draft, setDraft] = useState(blank);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<ServiceRequestRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uncertainAt, setUncertainAt] = useState<number | null>(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const generation = useRef(0);
  const state = loaded?.revision === revision ? loaded : null;
  const ready = !!state?.rows;
  const rows = state?.rows ?? [];
  const blocked = !ready || busy || uncertainAt !== null;
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; generation.current += 1; };
  }, []);

  function hideProtectedData() {
    generation.current += 1;
    setLoaded({ revision, error: "auth" });
    setSelected(null); setCreating(false); setDraft(blank()); setMessage(null); setUncertainAt(null);
  }

  useEffect(() => {
    const controller = new AbortController();
    const own = ++generation.current;
    const current = () => mounted.current && !controller.signal.aborted && own === generation.current;
    void loadServiceRequests(controller.signal).then((next) => {
      if (current()) setLoaded({ revision, rows: next });
    }).catch((error: unknown) => {
      if (!current()) return;
      if (error instanceof ServiceRequestError && error.kind === "auth") {
        generation.current += 1;
        setLoaded({ revision, error: "auth" }); setSelected(null); setCreating(false); setDraft(blank());
        setMessage(null); setUncertainAt(null);
      } else setLoaded({ revision, error: "read" });
    });
    return () => controller.abort();
  }, [revision]);

  function refresh() { if (!pending.current) setRevision((value) => value + 1); }

  async function command(action: () => Promise<ServiceRequestRow>, confirmed: () => void) {
    if (pending.current || blocked) return;
    pending.current = true; setBusy(true); setMessage(null);
    try {
      await action();
      if (!mounted.current) return;
      confirmed();
      setRevision((value) => value + 1);
    } catch (error) {
      if (!mounted.current) return;
      if (error instanceof ServiceRequestError && error.kind === "auth") hideProtectedData();
      else if (error instanceof ServiceRequestError && error.kind === "rejected") setMessage("Действие отклонено. Проверьте поля и права доступа. Введённые данные сохранены.");
      else {
        setUncertainAt(revision);
        setMessage("Результат действия не подтверждён. Обновите список и проверьте заявку перед повтором. Автоматической повторной отправки нет.");
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function move(event: DragEndEvent) {
    const id = Number(event.active.id), target = event.over ? String(event.over.id) : null;
    const row = rows.find((r) => r.id === id);
    if (!row || !target || row.status === target || blocked) return;
    if (!SERVICE_STATUSES.some((s) => s.id === target)) { setMessage("Этот статус доступен только для просмотра."); return; }
    void command(() => updateServiceRequest(id, { status: target }), () => setSelected(null));
  }

  const stages = serviceStages(rows);
  const q = query.trim().toLocaleLowerCase("ru");
  const visible = rows.filter((r) => (!statusFilter || r.status === statusFilter)
    && `${r.id} ${r.title} ${r.description}`.toLocaleLowerCase("ru").includes(q));
  const visibleIds = new Set(visible.map((r) => r.id));
  const columns = stages.filter((s) => !statusFilter || s.id === statusFilter);

  return <>
    <main className="flex-1 space-y-5 overflow-auto p-4 md:p-6" inert={selected !== null}>
      <header className="flex flex-wrap items-center gap-3">
        <div className="mr-auto"><h1 className="text-xl font-bold text-ink">Заявки на обслуживание</h1>
          <p className="mt-1 text-sm text-muted">Рабочие заявки сервиса. Откройте карточку или перенесите её в нужный статус.</p></div>
        <button type="button" className={button} disabled={busy} onClick={refresh}><RefreshCw size={16} />Обновить список</button>
        <button type="button" className={`${button} !border-accent !bg-accent !text-white`} disabled={blocked}
          onClick={() => setCreating((value) => !value)}><Plus size={16} />Создать заявку</button>
      </header>

      <section aria-label="Показатели сервисных заявок" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[{ label: "Новые", count: rows.filter((r) => r.status === "new").length },
          { label: "В работе", count: rows.filter((r) => r.status === "in_progress").length },
          { label: "Закрытые", count: rows.filter((r) => r.status === "done").length },
          { label: "SLA выполнен", count: null }].map(({ label, count }) => <div key={label} className="rounded-xl border border-line bg-surface p-4 shadow-card">
            <p className="text-sm text-muted">{label}</p><p className="mt-2 text-2xl font-semibold text-ink">{count === null ? "Нет данных" : ready ? count : "—"}</p>
            <p className="mt-2 text-xs text-muted">{count === null ? "Сроки и норматив SLA не подключены" : "По загруженным заявкам"}</p>
          </div>)}
      </section>

      <div className="flex flex-wrap gap-3 rounded-xl border border-line bg-surface p-3">
        <label className="relative min-w-52 flex-1"><span className="sr-only">Поиск заявок</span><Search size={16} className="absolute left-3 top-3 text-muted" />
          <input className={`${input} pl-9`} type="search" placeholder="Название, описание или номер" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <label className="min-w-44"><span className="sr-only">Статус заявок</span><select className={input} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Все статусы</option>{stages.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          {statusFilter && !stages.some((s) => s.id === statusFilter) && <option value={statusFilter}>Другой статус: {statusFilter}</option>}
        </select></label>
      </div>

      {message && <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{message}
        {uncertainAt !== null && <div className="mt-3 flex flex-wrap gap-2"><button type="button" className={button} onClick={refresh} disabled={busy}>Проверить список</button>
          <button type="button" className={button} disabled={!ready || revision <= uncertainAt} onClick={() => { setUncertainAt(null); setMessage(null); }}>Я проверил результат</button></div>}
      </div>}

      {creating && state?.error !== "auth" && <form aria-label="Новая сервисная заявка" className="space-y-4 rounded-xl border border-line bg-surface p-5 shadow-card"
        onSubmit={(e) => { e.preventDefault(); void command(() => createServiceRequest(draft), () => { setCreating(false); setDraft(blank()); }); }}>
        <h2 className="font-semibold text-ink">Новая заявка</h2>
        <label className="block text-sm text-muted">Заголовок<input className={`${input} mt-1`} required maxLength={255} value={draft.title} disabled={busy} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
        <label className="block text-sm text-muted">Описание<textarea className={`${input} mt-1 min-h-24`} value={draft.description} disabled={busy} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
        <label className="block text-sm text-muted">Приоритет<select className={`${input} mt-1`} value={draft.priority} disabled={busy} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}>
          {SERVICE_PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select></label>
        <p className="text-xs text-muted">Ручная заявка создаётся без привязки к клиенту или сделке.</p>
        <div className="flex gap-2"><button className={`${button} !bg-accent !text-white`} disabled={blocked || !draft.title.trim()}>{busy ? "Сохранение…" : "Сохранить заявку"}</button>
          <button type="button" className={button} disabled={busy} onClick={() => setCreating(false)}>Отмена</button></div>
      </form>}

      {!state && <p role="status" className="p-4 text-muted">Загрузка заявок…</p>}
      {state?.error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        {state.error === "auth" ? <>Доступ к заявкам не подтверждён. Проверьте вход и права. <Link href="/login" className="underline">Войти</Link></>
          : <>Не удалось загрузить заявки. Показатели и изменения недоступны. <button type="button" onClick={refresh} className="underline">Повторить загрузку</button></>}
      </div>}
      {ready && <section aria-label="Канбан сервисных заявок" className="space-y-3">
        <p className="text-xs text-muted">Показано: {visible.length} из {rows.length}. Показатели сверху относятся ко всему загруженному списку.</p>
        {visible.length === 0 && <p className="rounded-xl border border-dashed border-line p-5 text-sm text-muted">{rows.length ? "По выбранным условиям заявки не найдены." : "Заявок пока нет. Создайте первую заявку."}</p>}
        <DndContext sensors={sensors} onDragEnd={move}><div className="flex gap-4 overflow-x-auto pb-3 thin-scroll">
          {columns.map((stage) => <FunnelColumn key={stage.id} stage={{ ...stage, count: stage.cards.filter((c) => visibleIds.has(c.id)).length }} showSum={false}>
            {visible.filter((r) => r.status === stage.id).map((row) => <RequestCard key={row.id} row={row} blocked={busy || uncertainAt !== null} onOpen={() => setSelected(row)} />)}
          </FunnelColumn>)}
        </div></DndContext>
      </section>}
    </main>
    {selected && <RequestDetail key={selected.id} row={selected} blocked={blocked} busy={busy} message={message} onClose={() => setSelected(null)}
      onSave={(patch) => void command(() => updateServiceRequest(selected.id, patch), () => setSelected(null))} />}
  </>;
}

function RequestDetail({ row, blocked, busy, message, onClose, onSave }: {
  row: ServiceRequestRow; blocked: boolean; busy: boolean; onClose: () => void;
  message: string | null;
  onSave: (patch: { status?: string; priority?: string }) => void;
}) {
  const [status, setStatus] = useState(row.status), [priority, setPriority] = useState(row.priority);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  const changed = status !== row.status || priority !== row.priority;
  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30 p-2 md:p-4">
    <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="service-detail-title" tabIndex={-1}
      className="w-full max-w-xl space-y-5 overflow-auto rounded-2xl bg-surface p-6 shadow-pop outline-none"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) onClose();
        if (e.key === "Tab") {
          const nodes = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),a[href]') ?? []);
          const first = nodes[0], last = nodes[nodes.length - 1];
          if (first && e.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { e.preventDefault(); last?.focus(); }
          else if (first && !e.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { e.preventDefault(); first.focus(); }
        }
      }}>
      <div className="flex items-start justify-between gap-3"><div><p className="text-xs text-muted">Заявка SR-{row.id}</p><h2 id="service-detail-title" className="mt-1 text-xl font-semibold text-ink">{row.title}</h2></div>
        <button type="button" className={button} aria-label="Закрыть карточку" disabled={busy} onClick={onClose}><X size={16} /></button></div>
      <p className="whitespace-pre-wrap text-sm text-ink">{row.description || "Описание не указано"}</p>
      {message && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{message} При неподтверждённом результате закройте карточку и проверьте список.</p>}
      <p className="text-xs text-muted">Создана: {row.created_at.replace("T", " ")}</p>
      <div className="flex flex-wrap gap-3 text-sm text-accent">
        {row.counterparty_id !== null ? <Link className="underline" href={`/erp/spravochniki/counterparty/${row.counterparty_id}`}>Открыть клиента</Link> : <span className="text-muted">Клиент не привязан</span>}
        {row.deal_id !== null && <Link className="underline" href={`/crm/deals/${row.deal_id}`}>Связанная сделка</Link>}
      </div>
      <label className="block text-sm text-muted">Статус заявки<select className={`${input} mt-1`} value={status} disabled={blocked} onChange={(e) => setStatus(e.target.value)}>
        {!SERVICE_STATUSES.some((s) => s.id === row.status) && <option value={row.status}>Другой статус: {row.status}</option>}
        {SERVICE_STATUSES.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
      </select></label>
      <label className="block text-sm text-muted">Приоритет заявки<select className={`${input} mt-1`} value={priority} disabled={blocked} onChange={(e) => setPriority(e.target.value)}>
        {!SERVICE_PRIORITIES.some((p) => p.value === row.priority) && <option value={row.priority}>{row.priority}</option>}
        {SERVICE_PRIORITIES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
      </select></label>
      <button type="button" className={`${button} !bg-accent !text-white`} disabled={blocked || !changed}
        onClick={() => onSave({ ...(status !== row.status ? { status } : {}), ...(priority !== row.priority ? { priority } : {}) })}>{busy ? "Сохранение…" : "Сохранить изменения"}</button>
    </div>
  </div>;
}
