// frontend/src/components/leads/leads-workspace.tsx
"use client";

import clsx from "clsx";
import { Plus, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import {
  convertLead,
  createLead,
  type LeadInput,
  qualifyLead,
  routeLead,
} from "@/lib/api";
import type { Lead, LeadStatus } from "@/lib/types";

const SOURCES = ["site", "telegram", "whatsapp", "email", "phone", "tender"];
const SOURCE_LABELS: Record<string, string> = {
  site: "Сайт",
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  email: "E-mail",
  phone: "Телефон",
  tender: "Тендер",
};
const STATUS_META: Record<LeadStatus, { label: string; cls: string }> = {
  new: { label: "Новый", cls: "bg-blue-100 text-blue-700" },
  qualified: { label: "Квалифицирован", cls: "bg-violet-100 text-violet-700" },
  routed: { label: "Распределён", cls: "bg-amber-100 text-amber-700" },
  converted: { label: "В сделке", cls: "bg-green-100 text-green-700" },
  rejected: { label: "Отклонён", cls: "bg-slate-200 text-slate-600" },
};
const FUNNEL_LABELS: Record<string, string> = {
  new: "Новые клиенты",
  regular: "Постоянные",
  tender: "Тендеры",
  project: "Проектные",
};
const INPUT =
  "w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand";

// --- канбан-колонки по статусу лида (порядок = поток воронки) ---
const COLUMNS: { key: LeadStatus; title: string; color: string }[] = [
  { key: "new", title: "Новые лиды", color: "#3B82F6" },
  { key: "qualified", title: "Квалификация", color: "#8B5CF6" },
  { key: "routed", title: "Распределение", color: "#F59E0B" },
  { key: "converted", title: "Конвертированы", color: "#22C55E" },
  { key: "rejected", title: "Отклонены", color: "#94A3B8" },
];

// --- каналы: цвет иконки + порядок в строке «Каналы» ---
const CHANNELS = ["tender", "email", "phone", "telegram", "site", "whatsapp"];
const CH_COLOR: Record<string, string> = {
  tender: "#7C5CFC",
  email: "#7A828F",
  phone: "#2F6BFF",
  telegram: "#28A8E8",
  site: "#0E9F98",
  whatsapp: "#25D366",
};

function ChannelGlyph({ source }: { source: string }) {
  switch (source) {
    case "tender":
      return <path d="M3 21V8l9-5 9 5v13M9 21v-6h6v6" strokeLinejoin="round" />;
    case "email":
      return (
        <>
          <rect x="2" y="4" width="20" height="16" rx="2" />
          <path d="M3 6l9 7 9-7" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    case "phone":
      return (
        <path
          d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.4 1.8.7 2.7a2 2 0 01-.5 2.1L8.1 9.9a16 16 0 006 6l1.4-1.2a2 2 0 012.1-.4c.9.3 1.8.6 2.7.7a2 2 0 011.7 2z"
          strokeLinejoin="round"
        />
      );
    case "telegram":
      return (
        <path
          d="M21.5 4.3L2.5 11.6c-1 .4-1 1.7.1 2l4.8 1.5 1.8 5.6c.3.9 1.4 1 2 .3l2.6-2.7 4.9 3.6c.7.5 1.7.1 1.9-.8l3.3-15c.2-1-.8-1.7-1.7-1.3z"
          fill="currentColor"
          stroke="none"
        />
      );
    case "whatsapp":
      return (
        <path
          d="M12 2a10 10 0 00-8.5 15.2L2 22l4.9-1.3A10 10 0 1012 2zm4.4 12c-.2-.1-1.4-.7-1.6-.8s-.4-.1-.5.1l-.7.9c-.1.2-.3.2-.5.1a6.5 6.5 0 01-3.2-2.8c-.2-.4.2-.4.6-1.2a.4.4 0 000-.4l-.8-1.8c-.2-.5-.4-.4-.5-.4h-.5a.9.9 0 00-.7.3 2.8 2.8 0 00-.9 2.1 4.9 4.9 0 001 2.6 11 11 0 004.3 3.8c2 .8 2 .5 2.4.5a2.4 2.4 0 001.6-1.1 2 2 0 00.1-1.1c0-.1-.2-.2-.4-.3z"
          fill="currentColor"
          stroke="none"
        />
      );
    case "site":
    default:
      return (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a15 15 0 010 18M12 3a15 15 0 000 18" strokeLinecap="round" />
        </>
      );
  }
}

function ChannelIcon({ source, size = 18 }: { source: string; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-md"
      style={{ background: CH_COLOR[source] ?? "#64748B", width: size, height: size }}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="#fff"
        strokeWidth={2.2}
        style={{ width: size * 0.62, height: size * 0.62 }}
      >
        <ChannelGlyph source={source} />
      </svg>
    </span>
  );
}

function pluralLeads(n: number) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "лид";
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return "лида";
  return "лидов";
}

function StatusBadge({ status }: { status: LeadStatus }) {
  const m = STATUS_META[status];
  return <span className={clsx("rounded-full px-2 py-0.5 text-xs font-medium", m.cls)}>{m.label}</span>;
}

function ScoreBadge({ lead }: { lead: Lead }) {
  if (!lead.qualification) return <span className="text-sm text-slate-400">—</span>;
  const target = lead.qualification === "target";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        target ? "bg-green-100 text-green-700" : "bg-slate-200 text-slate-600",
      )}
      title={target ? "Целевой лид" : "Нецелевой лид"}
    >
      {lead.score} · {target ? "целевой" : "нецелевой"}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function KpiTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-white p-3 shadow-card">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold tracking-tight text-ink">{value}</div>
    </div>
  );
}

function Pin() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-slate-400">
      <path d="M12 21s-7-5.2-7-11a7 7 0 0114 0c0 5.8-7 11-7 11z" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="2.4" />
    </svg>
  );
}

function LeadCard({
  lead,
  selected,
  onSelect,
}: {
  lead: Lead;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={clsx(
        "cursor-pointer rounded-xl border bg-white p-3 shadow-card transition hover:shadow-pop",
        selected ? "border-brand ring-1 ring-brand" : "border-slate-100",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-slate-400">№ ЛИД-{lead.id}</span>
        <StatusBadge status={lead.status} />
      </div>
      <div className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-500">
        <ChannelIcon source={lead.source} size={18} />
        {SOURCE_LABELS[lead.source] ?? lead.source}
      </div>
      <div className="text-sm font-semibold leading-tight text-ink">
        {lead.company || lead.name || "Лид без имени"}
      </div>
      {lead.product && <div className="mt-0.5 text-xs text-muted">{lead.product}</div>}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-xs text-muted">
          <Pin />
          {lead.region || "—"}
        </span>
        {lead.qualification && <ScoreBadge lead={lead} />}
      </div>
    </div>
  );
}

function IntakeModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (input: LeadInput) => Promise<boolean>;
}) {
  const [form, setForm] = useState<LeadInput>({ source: "site" });
  const [saving, setSaving] = useState(false);

  function set<K extends keyof LeadInput>(key: K, value: LeadInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    await onCreate(form);
    setSaving(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-pop"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-ink">Принять лид</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Канал">
              <select value={form.source} onChange={(e) => set("source", e.target.value)} className={INPUT}>
                {SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {SOURCE_LABELS[s]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Регион">
              <input value={form.region ?? ""} onChange={(e) => set("region", e.target.value)} placeholder="Минск" className={INPUT} />
            </Field>
          </div>
          <Field label="Компания">
            <input value={form.company ?? ""} onChange={(e) => set("company", e.target.value)} placeholder="ООО ..." className={INPUT} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Контакт">
              <input value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} placeholder="Имя" className={INPUT} />
            </Field>
            <Field label="Телефон">
              <input value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} placeholder="+375 ..." className={INPUT} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="E-mail">
              <input value={form.email ?? ""} onChange={(e) => set("email", e.target.value)} placeholder="mail@..." className={INPUT} />
            </Field>
            <Field label="Интерес (продукт)">
              <input value={form.product ?? ""} onChange={(e) => set("product", e.target.value)} placeholder="лист, арматура..." className={INPUT} />
            </Field>
          </div>
          <Field label="Сообщение">
            <textarea value={form.message ?? ""} onChange={(e) => set("message", e.target.value)} rows={3} placeholder="Текст обращения клиента..." className={INPUT} />
          </Field>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600">
            Отмена
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
            {saving ? "Приём..." : "Принять"}
          </button>
        </div>
      </form>
    </div>
  );
}

function DetailPanel({
  lead,
  busy,
  onQualify,
  onRoute,
  onConvert,
}: {
  lead: Lead;
  busy: boolean;
  onQualify: () => void;
  onRoute: () => void;
  onConvert: () => void;
}) {
  const Action = ({ label, onClick, done }: { label: string; onClick: () => void; done: boolean }) => (
    <button
      onClick={onClick}
      disabled={busy || done}
      className={clsx(
        "w-full rounded-lg px-3 py-2 text-sm font-medium",
        done
          ? "bg-green-50 text-green-700"
          : "bg-brand text-white hover:bg-brand-700 disabled:opacity-60",
      )}
    >
      {done ? `✓ ${label}` : busy ? "..." : label}
    </button>
  );

  const qualified = lead.status !== "new";
  const routed = lead.status === "routed" || lead.status === "converted";
  const converted = lead.status === "converted";

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-ink">{lead.company || lead.name || "Лид без имени"}</h3>
          <StatusBadge status={lead.status} />
        </div>
        <div className="mt-1 text-xs text-muted">
          {SOURCE_LABELS[lead.source] ?? lead.source}
          {lead.region ? ` · ${lead.region}` : ""}
        </div>
      </div>

      <dl className="space-y-1.5 text-sm">
        {lead.name && lead.company && <Row k="Контакт" v={lead.name} />}
        {lead.phone && <Row k="Телефон" v={lead.phone} />}
        {lead.email && <Row k="E-mail" v={lead.email} />}
        {lead.product && <Row k="Интерес" v={lead.product} />}
      </dl>

      {lead.message && (
        <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{lead.message}</div>
      )}

      {/* Квалификация */}
      <div className="rounded-lg border border-slate-200 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Квалификация
          </span>
          <ScoreBadge lead={lead} />
        </div>
        {lead.reason ? (
          <p className="text-sm text-slate-600">{lead.reason}</p>
        ) : (
          <p className="text-sm text-slate-400">Ещё не оценён</p>
        )}
        {lead.aiRationale && (
          <div className="mt-2 rounded-lg bg-violet-50 p-2.5 text-sm text-violet-900">
            <span className="mr-1 rounded bg-violet-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
              AI
            </span>
            {lead.aiRationale}
          </div>
        )}
      </div>

      {/* Распределение */}
      {lead.assignedTo && (
        <div className="rounded-lg border border-slate-200 p-3 text-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Распределение
          </div>
          <div className="mt-1 text-ink">
            {lead.assignedTo}
            {lead.funnel ? ` · ${FUNNEL_LABELS[lead.funnel] ?? lead.funnel}` : ""}
          </div>
        </div>
      )}

      {/* Действия по этапам */}
      <div className="space-y-2">
        <Action label="Квалифицировать" onClick={onQualify} done={qualified} />
        <Action label="Распределить" onClick={onRoute} done={routed} />
        {converted && lead.dealId ? (
          <Link
            href={`/crm/deals/${lead.dealId}`}
            className="block w-full rounded-lg bg-green-50 px-3 py-2 text-center text-sm font-medium text-green-700 hover:bg-green-100"
          >
            Открыть сделку →
          </Link>
        ) : (
          <Action label="В сделку" onClick={onConvert} done={converted} />
        )}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{k}</dt>
      <dd className="text-right text-ink">{v}</dd>
    </div>
  );
}

export function LeadsWorkspace({ initialLeads }: { initialLeads: Lead[] }) {
  const [leads, setLeads] = useState<Lead[]>(initialLeads);
  const [selectedId, setSelectedId] = useState<number | null>(initialLeads[0]?.id ?? null);
  const [modalOpen, setModalOpen] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const selected = leads.find((l) => l.id === selectedId) ?? null;

  function patch(id: number, fields: Partial<Lead>) {
    setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, ...fields } : l)));
  }

  async function onQualify(id: number) {
    setBusyId(id);
    const res = await qualifyLead(id);
    if (res) {
      patch(id, {
        status: res.status,
        score: res.score,
        qualification: res.qualification,
        reason: res.reason,
        aiRationale: res.ai_rationale ?? undefined,
      });
    }
    setBusyId(null);
  }

  async function onRoute(id: number) {
    setBusyId(id);
    const res = await routeLead(id);
    if (res) patch(id, { status: res.status, assignedTo: res.assigned_to, funnel: res.funnel });
    setBusyId(null);
  }

  async function onConvert(id: number) {
    setBusyId(id);
    const res = await convertLead(id);
    if (res) patch(id, { status: "converted", dealId: res.deal_id });
    setBusyId(null);
  }

  async function onCreate(input: LeadInput): Promise<boolean> {
    const created = await createLead(input);
    if (!created) return false;
    setLeads((prev) => [created, ...prev]);
    setSelectedId(created.id);
    setModalOpen(false);
    return true;
  }

  const pending = leads.filter((l) => l.status === "new").length;

  // живые срезы из реальных лидов (без фейковых план/факт — у лида нет даты)
  const byStatus: Record<LeadStatus, Lead[]> = {
    new: [],
    qualified: [],
    routed: [],
    converted: [],
    rejected: [],
  };
  for (const l of leads) byStatus[l.status].push(l);

  const total = leads.length;
  const targetCount = leads.filter((l) => l.qualification === "target").length;
  const convertedCount = byStatus.converted.length;
  const conversion = total ? Math.round((convertedCount / total) * 100) : 0;
  const inWork = byStatus.new.length + byStatus.qualified.length + byStatus.routed.length;

  const channelCounts: Record<string, number> = {};
  for (const l of leads) channelCounts[l.source] = (channelCounts[l.source] ?? 0) + 1;

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-ink">Приём лидов</h1>
            <p className="mt-0.5 text-sm text-muted">
              Воронка: приём → квалификация → распределение → сделка · Новых: {pending} из {leads.length}.
            </p>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            <Plus size={16} /> Принять лид
          </button>
        </div>

        {leads.length > 0 && (
          <>
            {/* KPI — живые срезы */}
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KpiTile label="Всего лидов" value={total} />
              <KpiTile label="Новых" value={byStatus.new.length} />
              <KpiTile label="Целевых (скоринг)" value={targetCount} />
              <KpiTile label="Конверсия в сделку" value={`${conversion}%`} />
            </div>

            {/* Каналы — распределение текущих лидов */}
            <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl bg-white p-3 shadow-card">
              <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Каналы · текущие лиды
              </span>
              {CHANNELS.map((src) => (
                <span
                  key={src}
                  className="inline-flex items-center gap-2 rounded-lg border border-slate-100 bg-slate-50 px-2.5 py-1"
                >
                  <ChannelIcon source={src} size={20} />
                  <span className="text-xs font-medium text-slate-600">{SOURCE_LABELS[src]}</span>
                  <span className="text-sm font-bold text-ink">{channelCounts[src] ?? 0}</span>
                </span>
              ))}
              <span className="ml-auto text-xs font-semibold text-muted">
                Всего <b className="text-ink">{total}</b>
              </span>
            </div>
          </>
        )}

        {/* Канбан-воронка по статусу лида */}
        {leads.length === 0 ? (
          <div className="rounded-xl bg-white p-10 text-center text-sm text-muted shadow-card">
            Лидов пока нет — примите первый
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {COLUMNS.map((col) => {
              const items = byStatus[col.key];
              return (
                <div key={col.key} className="flex w-[280px] shrink-0 flex-col">
                  <div
                    className="mb-3 overflow-hidden rounded-xl border-t-[3px] bg-white p-3 shadow-card"
                    style={{ borderTopColor: col.color }}
                  >
                    <div className="flex items-center gap-2 text-sm font-bold text-ink">
                      <span className="h-2 w-2 rounded-full" style={{ background: col.color }} />
                      {col.title}
                    </div>
                    <div className="mt-1 text-xs text-muted">
                      <b className="text-ink">{items.length}</b> {pluralLeads(items.length)}
                    </div>
                  </div>
                  <div className="flex flex-col gap-3">
                    {items.map((l) => (
                      <LeadCard
                        key={l.id}
                        lead={l}
                        selected={l.id === selectedId}
                        onSelect={() => setSelectedId(l.id)}
                      />
                    ))}
                    {items.length === 0 && (
                      <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
                        —
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Итоги по воронке — живые срезы */}
        {leads.length > 0 && (
          <div className="mt-5 grid grid-cols-2 gap-4 rounded-xl bg-white p-4 shadow-card sm:grid-cols-4">
            <Metric label="Лидов в работе" value={inWork} />
            <Metric label="Конвертировано" value={convertedCount} />
            <Metric label="Целевых" value={targetCount} />
            <Metric label="Конверсия" value={`${conversion}%`} />
          </div>
        )}
      </main>

      <aside className="w-[340px] shrink-0 overflow-auto border-l border-slate-200 bg-white">
        {selected ? (
          <DetailPanel
            lead={selected}
            busy={busyId === selected.id}
            onQualify={() => onQualify(selected.id)}
            onRoute={() => onRoute(selected.id)}
            onConvert={() => onConvert(selected.id)}
          />
        ) : (
          <div className="p-6 text-sm text-muted">Выберите лид, чтобы квалифицировать и распределить.</div>
        )}
      </aside>

      {modalOpen && <IntakeModal onClose={() => setModalOpen(false)} onCreate={onCreate} />}
    </>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-xl font-bold tracking-tight text-ink">{value}</div>
    </div>
  );
}
