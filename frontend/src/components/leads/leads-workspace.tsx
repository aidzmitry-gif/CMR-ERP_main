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

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-ink">Приём лидов</h1>
            <p className="mt-0.5 text-sm text-muted">
              Вход воронки: приём → AI-квалификация → распределение → сделка. Новых: {pending} из {leads.length}.
            </p>
          </div>
          <button
            onClick={() => setModalOpen(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            <Plus size={16} /> Принять лид
          </button>
        </div>

        <div className="overflow-hidden rounded-xl bg-white shadow-card">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-100 text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Канал</th>
                <th className="px-4 py-2.5 font-medium">Компания / контакт</th>
                <th className="px-4 py-2.5 font-medium">Регион</th>
                <th className="px-4 py-2.5 font-medium">Интерес</th>
                <th className="px-4 py-2.5 font-medium">Оценка</th>
                <th className="px-4 py-2.5 font-medium">Статус</th>
              </tr>
            </thead>
            <tbody>
              {leads.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted">
                    Лидов пока нет — примите первый
                  </td>
                </tr>
              )}
              {leads.map((lead) => (
                <tr
                  key={lead.id}
                  onClick={() => setSelectedId(lead.id)}
                  className={clsx(
                    "cursor-pointer border-b border-slate-50 last:border-0 hover:bg-slate-50",
                    selectedId === lead.id && "bg-brand-100/40",
                  )}
                >
                  <td className="px-4 py-2.5 text-slate-600">{SOURCE_LABELS[lead.source] ?? lead.source}</td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-ink">{lead.company || lead.name || "—"}</div>
                    {lead.company && lead.name && <div className="text-xs text-muted">{lead.name}</div>}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600">{lead.region || "—"}</td>
                  <td className="px-4 py-2.5 text-slate-600">{lead.product || "—"}</td>
                  <td className="px-4 py-2.5">
                    <ScoreBadge lead={lead} />
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={lead.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
