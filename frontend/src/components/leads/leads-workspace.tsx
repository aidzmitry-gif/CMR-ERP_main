// frontend/src/components/leads/leads-workspace.tsx
"use client";

import clsx from "clsx";
import { Globe, Mail, Phone, Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { CallWindow } from "@/components/calls/call-window";
import { LeadDrawerPreview } from "@/components/leads/lead-drawer-preview";
import {
  convertLead,
  createLead,
  expressLead,
  fetchLeadManagers,
  fetchLeadsClient,
  LeadDuplicateError,
  type LeadInput,
  qualifyLead,
  rejectLead,
  routeLead,
  submitEmailLead,
  submitWebLead,
} from "@/lib/api";
import { formatByn } from "@/lib/format";
import { DEFAULT_NEXT_STEP_PRESET_KEY, NEXT_STEP_PRESETS } from "@/lib/lead-next-step";
import type { Lead, LeadStatus, Manager } from "@/lib/types";

// Порог балла для кнопки «⚡ Экспресс» на карточке «Новые» — совпадает с QUALIFY_THRESHOLD
// бэка (modules/leads/leads.py): показываем экспресс только для уже явно целевых лидов,
// чтобы не ловить 422 «не целевой» на кнопке.
const EXPRESS_SCORE_THRESHOLD = 50;

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
  rejected: { label: "Отклонён", cls: "bg-sunken text-muted" },
};
const INPUT =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent";

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
  if (!lead.qualification) return <span className="text-sm text-faint">—</span>;
  const target = lead.qualification === "target";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        target ? "bg-green-100 text-green-700" : "bg-sunken text-muted",
      )}
      title={target ? "Целевой лид" : "Нецелевой лид"}
    >
      {lead.score} · {target ? "целевой" : "нецелевой"}
    </span>
  );
}

// Чип ожидания реакции (SLA первой реакции, Цикл 1): минуты с приёма лида,
// часы — когда ожидание затянулось (>90 мин); >15 мин подсвечивается как задержка.
function waitingMinutes(createdAt?: string): number | null {
  if (!createdAt) return null;
  const created = new Date(createdAt.endsWith("Z") ? createdAt : `${createdAt}Z`).getTime();
  if (Number.isNaN(created)) return null;
  return Math.max(0, Math.round((Date.now() - created) / 60000));
}

function formatWait(minutes: number): string {
  return minutes > 90 ? `${Math.round(minutes / 60)} ч` : `${minutes} мин`;
}

function WaitChip({ createdAt }: { createdAt?: string }) {
  const minutes = waitingMinutes(createdAt);
  if (minutes == null) return null;
  const overdue = minutes > 15;
  return (
    <span
      title="Ожидает реакции с момента приёма"
      className={clsx(
        "inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold",
        overdue ? "bg-red-100 text-red-700" : "bg-sunken text-muted",
      )}
    >
      ⏱ {formatWait(minutes)}
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
    </label>
  );
}

function KpiTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-surface p-3 shadow-card">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold tracking-tight text-ink">{value}</div>
    </div>
  );
}

function Pin() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-faint">
      <path d="M12 21s-7-5.2-7-11a7 7 0 0114 0c0 5.8-7 11-7 11z" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="2.4" />
    </svg>
  );
}

// Контекстная кнопка следующего шага прямо на карточке (Слайс 1 кокпита лидов):
// одна кнопка под текущий статус вместо захода в drawer — new→qualify, qualified→route,
// routed→convert. converted/rejected — терминальные, кнопки нет.
const NEXT_ACTION: Record<LeadStatus, { label: string; key: "qualify" | "route" | "convert" } | null> = {
  new: { label: "✅ Квалифицировать", key: "qualify" },
  qualified: { label: "🤝 Распределить", key: "route" },
  routed: { label: "⚡ В сделку", key: "convert" },
  converted: null,
  rejected: null,
};

// Поповер экспресс-передачи (Цикл 2): менеджер (авто/выбор) + пресет следующего шага +
// «Передать» — 2 клика с карточки вместо qualify→route по отдельности. Открывается
// прямо у карточки «Новые» (score >= EXPRESS_SCORE_THRESHOLD), без захода в drawer.
function ExpressPopover({
  leadId,
  onClose,
  onExpress,
}: {
  leadId: number;
  onClose: () => void;
  onExpress: (
    id: number,
    opts: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
  ) => Promise<string | null>;
}) {
  const [managers, setManagers] = useState<Manager[]>([]);
  const [managersLoading, setManagersLoading] = useState(true);
  const [selectedManager, setSelectedManager] = useState("");
  const [presetKey, setPresetKey] = useState(DEFAULT_NEXT_STEP_PRESET_KEY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchLeadManagers().then((list) => {
      if (!cancelled) {
        setManagers(list);
        setManagersLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const preset = NEXT_STEP_PRESETS.find((p) => p.key === presetKey) ?? NEXT_STEP_PRESETS[0];

  async function submit() {
    setBusy(true);
    setError(null);
    const at = preset.at();
    const err = await onExpress(leadId, {
      assignedTo: selectedManager || undefined,
      nextStepAt: at || undefined,
      nextStepNote: at ? preset.note : undefined,
    });
    setBusy(false);
    if (err) setError(err);
  }

  return (
    <div
      data-card-action
      onClick={(e) => e.stopPropagation()}
      className="absolute inset-x-0 top-full z-30 mt-1.5 rounded-xl border border-line bg-surface p-3 shadow-pop"
    >
      <div className="mb-2">
        <div className="mb-1 text-[11px] font-semibold text-muted">Кому</div>
        <select
          value={selectedManager}
          onChange={(e) => setSelectedManager(e.target.value)}
          disabled={managersLoading}
          className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-ink outline-none focus:border-accent disabled:opacity-60"
        >
          <option value="">Авто (по правилам)</option>
          {managers.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      </div>
      <div className="mb-2 flex flex-wrap gap-1">
        {NEXT_STEP_PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPresetKey(p.key)}
            className={clsx(
              "rounded-full border px-2 py-1 text-[11px] font-medium",
              presetKey === p.key
                ? "border-accent bg-accent-soft text-accent-ink"
                : "border-line text-muted hover:bg-sunken",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>
      {error && (
        <div className="mb-2 rounded-lg bg-red-100 px-2 py-1.5 text-[11px] text-red-700">{error}</div>
      )}
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 rounded-lg border border-line py-1.5 text-xs font-medium text-muted hover:bg-sunken"
        >
          Отмена
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={submit}
          className="flex-1 rounded-lg bg-accent py-1.5 text-xs font-semibold text-white hover:bg-accent-ink disabled:opacity-60"
        >
          {busy ? "..." : "Передать"}
        </button>
      </div>
    </div>
  );
}

function LeadCard({
  lead,
  selected,
  busy,
  expressOpen,
  onPreview,
  onOpen,
  onCall,
  onQualify,
  onRoute,
  onConvert,
  onToggleExpress,
  onExpress,
}: {
  lead: Lead;
  selected: boolean;
  busy: boolean;
  expressOpen: boolean;
  onPreview: () => void;
  onOpen: () => void;
  onCall: () => void;
  onQualify: () => void;
  onRoute: () => void;
  onConvert: () => void;
  onToggleExpress: () => void;
  onExpress: (
    id: number,
    opts: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
  ) => Promise<string | null>;
}) {
  // Click vs double-click split: 1 клик → drawer-preview справа,
  // 2 клика → полная страница /crm/leads/[id]. Кнопка «📞» — отдельная,
  // не должна триггерить выбор/навигацию.
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (clickTimer.current) clearTimeout(clickTimer.current);
    },
    [],
  );

  function handleClick(e: React.MouseEvent) {
    const target = e.target as HTMLElement;
    if (target.closest("[data-card-action]")) return;
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
      onOpen();
      return;
    }
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      onPreview();
    }, 230);
  }

  const canExpress = lead.status === "new" && lead.score >= EXPRESS_SCORE_THRESHOLD;

  return (
    <div
      onClick={handleClick}
      className={clsx(
        "relative cursor-pointer rounded-xl border bg-surface p-3 shadow-card transition hover:shadow-pop",
        selected ? "border-accent ring-1 ring-accent" : "border-line",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-faint">№ ЛИД-{lead.id}</span>
        <div className="flex items-center gap-1.5">
          {lead.status === "new" && <WaitChip createdAt={lead.createdAt} />}
          <StatusBadge status={lead.status} />
        </div>
      </div>
      <div className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-semibold text-muted">
        <ChannelIcon source={lead.source} size={18} />
        {SOURCE_LABELS[lead.source] ?? lead.source}
      </div>
      <div className="text-sm font-semibold leading-tight text-ink">
        {lead.company || lead.name || "Лид без имени"}
      </div>
      {lead.product && <div className="mt-0.5 text-xs text-muted">{lead.product}</div>}
      {(lead.itemsCount ?? 0) > 0 && (
        <div
          className="mt-1.5 inline-flex items-center gap-1 rounded-md bg-money-soft px-1.5 py-0.5 text-[11px] font-semibold text-money"
          title="Подобранный КП: позиции и сумма"
        >
          🧾 {lead.itemsCount} поз. · {formatByn(lead.itemsTotal ?? 0)}
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1 text-xs text-muted">
          <Pin />
          {lead.region || "—"}
        </span>
        <div className="flex items-center gap-1.5">
          {lead.qualification && <ScoreBadge lead={lead} />}
          {lead.phone && (
            <button
              type="button"
              data-card-action
              onClick={(e) => {
                e.stopPropagation();
                onCall();
              }}
              aria-label="Позвонить"
              title={`Позвонить ${lead.phone}`}
              className="flex h-7 w-7 items-center justify-center rounded-md bg-money text-white hover:brightness-105"
            >
              <Phone size={13} />
            </button>
          )}
        </div>
      </div>
      {(NEXT_ACTION[lead.status] || canExpress) && (
        <div className="mt-2 flex gap-1.5">
          {NEXT_ACTION[lead.status] && (
            <button
              type="button"
              data-card-action
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                const action = NEXT_ACTION[lead.status];
                if (!action) return;
                if (action.key === "qualify") onQualify();
                else if (action.key === "route") onRoute();
                else onConvert();
              }}
              className="flex-1 rounded-lg bg-accent-soft py-1.5 text-xs font-semibold text-accent-ink hover:bg-accent hover:text-white disabled:opacity-60"
            >
              {busy ? "..." : NEXT_ACTION[lead.status]?.label}
            </button>
          )}
          {canExpress && (
            <button
              type="button"
              data-card-action
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpress();
              }}
              className="flex-1 rounded-lg border border-accent bg-surface py-1.5 text-xs font-semibold text-accent-ink hover:bg-accent-soft disabled:opacity-60"
            >
              ⚡ Экспресс
            </button>
          )}
        </div>
      )}
      {expressOpen && <ExpressPopover leadId={lead.id} onClose={onToggleExpress} onExpress={onExpress} />}
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
        className="w-full max-w-md rounded-2xl bg-surface p-5 shadow-pop"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-ink">Принять лид</h3>
          <button type="button" onClick={onClose} className="text-faint hover:text-muted">
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
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted">
            Отмена
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
            {saving ? "Приём..." : "Принять"}
          </button>
        </div>
      </form>
    </div>
  );
}

export function LeadsWorkspace({ initialLeads }: { initialLeads: Lead[] }) {
  const router = useRouter();
  const [leads, setLeads] = useState<Lead[]>(initialLeads);
  // selectedId = открыт drawer-preview по этому лиду (1-клик); первый лид
  //   открыт по умолчанию, чтобы был визуальный фокус сразу при заходе.
  const [selectedId, setSelectedId] = useState<number | null>(initialLeads[0]?.id ?? null);
  const [modalOpen, setModalOpen] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  // expressOpenId = у какой карточки открыт поповер экспресс-передачи (Цикл 2)
  const [expressOpenId, setExpressOpenId] = useState<number | null>(null);
  // callPopupLead = открыт screen-pop звонка по этому лиду
  //   (см. memory sales-call-window-reserve: real telephony — SALES-50-out, тут MVP UI).
  const [callPopupLead, setCallPopupLead] = useState<Lead | null>(null);

  const selected = leads.find((l) => l.id === selectedId) ?? null;

  const [note, setNote] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);

  async function refresh() {
    setLeads(await fetchLeadsClient());
  }

  // Демо: внешний канал (сайт/почта) шлёт заявку в публичный коннектор → лид приходит
  // событием через relay (~2с), затем подтягиваем приём.
  async function demoSite() {
    setDemoBusy(true);
    await submitWebLead({
      name: "Андрей Гудков",
      company: "ООО СтройКуб",
      phone: "+375297778899",
      email: "a.gudkov@stroykub.by",
      region: "Брест",
      product: "лист 5 мм",
      message: "Заявка с сайта: нужен лист 5 мм, 10 т, срочно",
    });
    setNote("Заявка с сайта принята — лид появится в «Новых» через пару секунд…");
    window.setTimeout(() => {
      void refresh();
      setNote("");
    }, 2600);
    setDemoBusy(false);
  }

  async function demoEmail() {
    setDemoBusy(true);
    await submitEmailLead({
      from: "Ольга Минина <o.minina@zavod.by>",
      subject: "Запрос цены на арматуру",
      text: "Здравствуйте, пришлите цену на арматуру 12, объём 8 т.",
    });
    setNote("Письмо принято — лид появится в «Новых» через пару секунд…");
    window.setTimeout(() => {
      void refresh();
      setNote("");
    }, 2600);
    setDemoBusy(false);
  }

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

  async function onRoute(
    id: number,
    opts?: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
  ) {
    setBusyId(id);
    const res = await routeLead(id, opts);
    if (res) patch(id, { status: res.status, assignedTo: res.assigned_to, funnel: res.funnel });
    setBusyId(null);
  }

  // Экспресс-передача (Цикл 2): квалификация + раздача + следующий шаг одним вызовом.
  // Возвращает текст ошибки (для поповера) или null при успехе — лид уезжает в «Распределение».
  async function onExpress(
    id: number,
    opts: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
  ): Promise<string | null> {
    setBusyId(id);
    const res = await expressLead(id, opts);
    setBusyId(null);
    if (res == null) return "Не удалось выполнить экспресс-передачу — попробуйте ещё раз";
    if ("error" in res) return res.error;
    setLeads((prev) => prev.map((l) => (l.id === id ? res : l)));
    setExpressOpenId(null);
    setNote(`Лид ЛИД-${id} передан ${res.assignedTo || "менеджеру"} — экспресс`);
    window.setTimeout(() => setNote(""), 3000);
    return null;
  }

  async function onConvert(id: number) {
    setBusyId(id);
    const res = await convertLead(id);
    if (res) patch(id, { status: "converted", dealId: res.deal_id });
    setBusyId(null);
  }

  async function onReject(id: number, reason: string) {
    setBusyId(id);
    const res = await rejectLead(id, reason);
    if (res) patch(id, { status: "rejected", rejectReason: res.reject_reason });
    setBusyId(null);
  }

  async function onCreate(input: LeadInput): Promise<boolean> {
    try {
      const created = await createLead(input);
      if (!created) return false;
      setLeads((prev) => [created, ...prev]);
      setSelectedId(created.id);
      setModalOpen(false);
      return true;
    } catch (e) {
      if (e instanceof LeadDuplicateError) {
        // дубль по телефону/e-mail — не плодим новый, открываем существующий лид
        setModalOpen(false);
        setSelectedId(e.duplicateOf);
        setNote(`Дубль лида #${e.duplicateOf} — уже есть в работе, открыт в панели`);
        window.setTimeout(() => setNote(""), 4000);
        return true;
      }
      return false;
    }
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

  // SLA первой реакции (Цикл 1): сколько новых лидов ждут дольше 15 мин + средняя
  // скорость реакции лидоруба сегодня (по лидам с уже проставленным first_action_at).
  const waitingOver15 = byStatus.new.filter((l) => (waitingMinutes(l.createdAt) ?? 0) > 15).length;
  const todayUtc = new Date().toISOString().slice(0, 10);
  const reactionTimesToday = leads
    .filter((l) => l.createdAt && l.firstActionAt?.startsWith(todayUtc))
    .map((l) =>
      Math.round(
        (new Date(`${l.firstActionAt}Z`).getTime() - new Date(`${l.createdAt}Z`).getTime()) / 60000,
      ),
    )
    .filter((m) => m >= 0);
  const avgReactionToday = reactionTimesToday.length
    ? Math.round(reactionTimesToday.reduce((a, b) => a + b, 0) / reactionTimesToday.length)
    : null;

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-ink">Приём лидов</h1>
            <p className="mt-0.5 text-sm text-muted">
              Воронка: приём → квалификация → распределение → сделка · Новых: {pending} из {leads.length}.
            </p>
            {note && <p className="mt-1 text-xs font-medium text-accent-ink">{note}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={demoSite}
              disabled={demoBusy}
              title="Симуляция: контакт-форма сайта → приём лида"
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
            >
              <Globe size={15} /> Заявка с сайта
            </button>
            <button
              onClick={demoEmail}
              disabled={demoBusy}
              title="Симуляция: входящее письмо → приём лида"
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
            >
              <Mail size={15} /> Письмо
            </button>
            <button
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent-ink"
            >
              <Plus size={16} /> Принять лид
            </button>
          </div>
        </div>

        {leads.length > 0 && (
          <>
            {/* KPI — живые срезы */}
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KpiTile label="Всего лидов" value={total} />
              <KpiTile label="Новых" value={byStatus.new.length} />
              <KpiTile label="Целевых (скоринг)" value={targetCount} />
              <KpiTile label="Конверсия в сделку" value={`${conversion}%`} />
              <KpiTile label="Ждут реакции >15м" value={waitingOver15} />
              {avgReactionToday != null && (
                <KpiTile label="Реакция сегодня" value={`~${avgReactionToday} мин`} />
              )}
            </div>

            {/* Каналы — распределение текущих лидов */}
            <div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl bg-surface p-3 shadow-card">
              <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Каналы · текущие лиды
              </span>
              {CHANNELS.map((src) => (
                <span
                  key={src}
                  className="inline-flex items-center gap-2 rounded-lg border border-line bg-sunken px-2.5 py-1"
                >
                  <ChannelIcon source={src} size={20} />
                  <span className="text-xs font-medium text-muted">{SOURCE_LABELS[src]}</span>
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
          <div className="rounded-xl bg-surface p-10 text-center text-sm text-muted shadow-card">
            Лидов пока нет — примите первый
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {COLUMNS.map((col) => {
              const items = byStatus[col.key];
              return (
                <div key={col.key} className="flex w-[280px] shrink-0 flex-col">
                  <div
                    className="mb-3 overflow-hidden rounded-xl border-t-[3px] bg-surface p-3 shadow-card"
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
                        busy={busyId === l.id}
                        expressOpen={expressOpenId === l.id}
                        onPreview={() => setSelectedId(l.id)}
                        onOpen={() => router.push(`/crm/leads/${l.id}`)}
                        onCall={() => setCallPopupLead(l)}
                        onQualify={() => onQualify(l.id)}
                        onRoute={() => onRoute(l.id)}
                        onConvert={() => onConvert(l.id)}
                        onToggleExpress={() => setExpressOpenId((prev) => (prev === l.id ? null : l.id))}
                        onExpress={onExpress}
                      />
                    ))}
                    {items.length === 0 && (
                      <div className="rounded-xl border border-dashed border-line p-4 text-center text-xs text-faint">
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
          <div className="mt-5 grid grid-cols-2 gap-4 rounded-xl bg-surface p-4 shadow-card sm:grid-cols-4">
            <Metric label="Лидов в работе" value={inWork} />
            <Metric label="Конвертировано" value={convertedCount} />
            <Metric label="Целевых" value={targetCount} />
            <Metric label="Конверсия" value={`${conversion}%`} />
          </div>
        )}
      </main>

      {/* Drawer-preview вместо постоянной правой колонки: 1 клик по лиду открывает,
          2 клика уводят на /crm/leads/[id]. Первый лид открыт по умолчанию (см.
          useState(initialLeads[0]?.id)). */}
      <LeadDrawerPreview
        lead={selected}
        busy={busyId === selected?.id}
        onClose={() => setSelectedId(null)}
        onQualify={onQualify}
        onRoute={onRoute}
        onConvert={onConvert}
        onReject={onReject}
        onCall={(l) => setCallPopupLead(l)}
        onItemsSaved={(id, count, total) => patch(id, { itemsCount: count, itemsTotal: total })}
        onConverted={(id, dealId) => patch(id, { status: "converted", dealId })}
      />

      {/* Единое окно звонка (call-window): тот же кокпит, что и в сделках, со скриптом лида,
          подбором товара и сбором позиций в сделку. Открывается с «📞» на карточке/в drawer. */}
      <CallWindow
        context={
          callPopupLead
            ? {
                kind: "lead",
                leadId: callPopupLead.id,
                company: callPopupLead.company,
                person: callPopupLead.name,
                phone: callPopupLead.phone,
                product: callPopupLead.product,
              }
            : null
        }
        onClose={() => setCallPopupLead(null)}
      />

      {/* Подсказка «Выберите лид» когда нет лидов вовсе — для пустого инбокса. */}
      {leads.length === 0 && (
        <aside className="w-[280px] shrink-0 overflow-auto border-l border-line bg-surface">
          <div className="p-6 text-sm text-muted">
            Выберите лид, чтобы квалифицировать и распределить.
          </div>
        </aside>
      )}

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
