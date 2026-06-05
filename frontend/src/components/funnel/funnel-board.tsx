"use client";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import clsx from "clsx";
import {
  Camera,
  Check,
  FileText,
  Flag,
  LayoutGrid,
  List,
  Mail,
  Plus,
  Printer,
  ScanLine,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { FaTelegramPlane, FaWeixin, FaWhatsapp } from "react-icons/fa";
import { useEffect, useMemo, useState } from "react";
import { createFunnelCard, fetchFunnelBoard, moveFunnelCard } from "@/lib/funnel-api";
import { formatMoney } from "@/lib/format";
import type {
  FunnelCard,
  FunnelKpi,
  FunnelPanel,
  FunnelStage,
  FunnelSummaryMetric,
  FunnelTone,
} from "@/lib/types";

export interface FunnelFieldDef {
  key: string;
  label: string;
  type?: "text" | "number";
  default?: string | number;
}

export interface FunnelDetailExtras {
  /** обеспеченность материалами (BOM) — для производства */
  bom?: { name: string; need: number; stock: number }[];
  /** загрузка оборудования, % — для производства */
  equipment?: { name: string; load: number }[];
  /** план/факт по операциям — для производства */
  operations?: { name: string; plan: string; fact: string; status: "ok" | "warn" | "bad" }[];
  /** прогноз риска — для производства */
  risk?: { percent: number; notes: string[] };
}

export interface FunnelBoardProps {
  title: string;
  subtitle?: string;
  boardPath: string; // GET  /api{boardPath}
  createPath: string; // POST /api{createPath}
  patchPath: string; // PATCH /api{patchPath}/{id}
  fields: FunnelFieldDef[];
  /** подпись основной кнопки («Создать закупку», «Создать наряд» …) */
  createLabel?: string;
  /** показывать денежные суммы (для HR/производства/обучения — false) */
  showSum?: boolean;
  /** верхние плитки «План/Факт» */
  kpis?: FunnelKpi[];
  /** строка статуса над доской (AI ведёт N · просрочки · период) */
  statusNote?: string;
  /** AI-инсайт-строка (фиолетовая плашка над доской) */
  insight?: string;
  /** правая панель (AI-лента / чаты / дедлайны) */
  panel?: FunnelPanel;
  /** нижние итоги с дельтами; если не заданы — считаются из доски */
  summary?: FunnelSummaryMetric[];
  /** доп. блоки в drawer карточки (BOM / оборудование) — командный центр производства */
  detailExtras?: FunnelDetailExtras;
  /** показать «Конверсию по воронке» из реальных счётчиков стадий (HR) */
  conversion?: boolean;
  /** лидерборд (топ-рекрутёры и т.п.) — демо-блок под итогами */
  leaderboard?: { name: string; meta: string; value: string }[];
  /** статичный ряд иконок каналов связи на карточках (закупки) */
  showChannels?: boolean;
  /** пилюли «Фокус / Приоритет» на карточках (HR / офис / юр) */
  showFocusPills?: boolean;
  /** мини-иконки действий на карточках (склад) */
  showActions?: boolean;
  /** табы над доской (база знаний: «Все курсы · Новые · …») + переключатель Сетка/Список */
  boardTabs?: string[];
}

const PRIORITY_TONE: Record<string, string> = {
  Высокий: "bg-red-50 text-red-600",
  Срочно: "bg-red-50 text-red-600",
  Средний: "bg-amber-50 text-amber-600",
  Контроль: "bg-amber-50 text-amber-600",
  Низкий: "bg-slate-100 text-slate-500",
  Обычный: "bg-slate-100 text-slate-500",
};

// Цвет бейджа по типу контента (база знаний) — как в референсе.
const CONTENT_TONE: Record<string, string> = {
  Видео: "bg-blue-50 text-blue-600",
  Тест: "bg-violet-50 text-violet-600",
  Документ: "bg-slate-100 text-slate-600",
  Практика: "bg-emerald-50 text-emerald-600",
  Обязательно: "bg-red-50 text-red-600",
};

const TONE_CHIP: Record<FunnelTone, string> = {
  blue: "bg-blue-50 text-blue-600",
  indigo: "bg-indigo-50 text-indigo-600",
  green: "bg-emerald-50 text-emerald-600",
  cyan: "bg-cyan-50 text-cyan-600",
  slate: "bg-slate-100 text-slate-500",
  amber: "bg-amber-50 text-amber-600",
  violet: "bg-violet-50 text-violet-600",
  red: "bg-red-50 text-red-600",
};

const TONE_BAR: Record<FunnelTone, string> = {
  blue: "bg-blue-500",
  indigo: "bg-indigo-500",
  green: "bg-emerald-500",
  cyan: "bg-cyan-500",
  slate: "bg-slate-400",
  amber: "bg-amber-500",
  violet: "bg-violet-500",
  red: "bg-red-500",
};

const PANEL_TONE: Record<string, string> = {
  ai: "bg-violet-500",
  alert: "bg-red-500",
  info: "bg-blue-500",
  ok: "bg-emerald-500",
};

// Каналы связи с поставщиком/контактом (статичный ряд иконок — как в референсах).
const CHANNELS: { key: string; color: string; Icon: React.ComponentType<{ size?: number }> }[] = [
  { key: "wechat", color: "#09B83E", Icon: FaWeixin },
  { key: "whatsapp", color: "#25D366", Icon: FaWhatsapp },
  { key: "telegram", color: "#229ED9", Icon: FaTelegramPlane },
  { key: "email", color: "#3B82F6", Icon: Mail },
];

// Цвет статус-чипа карточки (курсы базы знаний и т.п.).
const STATE_TONE: Record<string, string> = {
  Пройдено: "bg-emerald-50 text-emerald-600",
  "В процессе": "bg-blue-50 text-blue-600",
  "Не начат": "bg-slate-100 text-slate-500",
  Заблокировано: "bg-slate-100 text-slate-400",
};

// Мини-иконки действий на карточке (склад: документ/штрихкод/печать/фото).
const ACTION_ICONS: React.ComponentType<{ size?: number }>[] = [FileText, ScanLine, Printer, Camera];

function initials(name: string): string {
  return name
    .replace(/[«»"]/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

function blankForm(fields: FunnelFieldDef[]): Record<string, string | number> {
  return Object.fromEntries(fields.map((f) => [f.key, f.default ?? (f.type === "number" ? 0 : "")]));
}

function recompute(stages: FunnelStage[]): FunnelStage[] {
  return stages.map((s) => ({
    ...s,
    count: s.cards.length,
    sum: s.cards.reduce((a, c) => a + (c.amount ?? 0), 0),
  }));
}

function moveCard(stages: FunnelStage[], cardId: number, targetStage: string): FunnelStage[] {
  const source = stages.find((s) => s.cards.some((c) => c.id === cardId));
  if (!source || source.id === targetStage) return stages;
  const card = source.cards.find((c) => c.id === cardId);
  if (!card) return stages;
  return recompute(
    stages.map((s) => {
      if (s.id === source.id) return { ...s, cards: s.cards.filter((c) => c.id !== cardId) };
      if (s.id === targetStage) return { ...s, cards: [...s.cards, card] };
      return s;
    }),
  );
}

function KpiTile({ kpi }: { kpi: FunnelKpi }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-card">
      <div className="flex items-center gap-2">
        <span className={clsx("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", TONE_CHIP[kpi.tone])}>
          <span className="h-2 w-2 rounded-full bg-current" />
        </span>
        <span className="text-xs leading-tight text-muted">{kpi.label}</span>
      </div>
      <div className="mt-3 text-lg font-semibold text-ink">
        {kpi.value}
        {kpi.target && <span className="text-sm font-normal text-muted"> / {kpi.target}</span>}
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div className={clsx("h-full rounded-full", TONE_BAR[kpi.tone])} style={{ width: `${kpi.percent}%` }} />
      </div>
      <div className="mt-1.5 text-xs text-muted">{kpi.note}</div>
    </div>
  );
}

function Card({
  card,
  onOpen,
  showChannels,
  showFocusPills,
  showActions,
}: {
  card: FunnelCard;
  onOpen?: () => void;
  showChannels?: boolean;
  showFocusPills?: boolean;
  showActions?: boolean;
}) {
  return (
    <div
      onClick={onOpen}
      className={clsx(
        "rounded-xl bg-white p-3.5 shadow-card transition-shadow hover:shadow-pop",
        onOpen && "cursor-pointer",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs text-muted">№ {card.code}</span>
        <div className="flex shrink-0 items-center gap-1.5">
          {card.state && (
            <span className={clsx("rounded-md px-2 py-0.5 text-[11px] font-medium", STATE_TONE[card.state] ?? "bg-slate-100 text-slate-500")}>
              {card.state}
            </span>
          )}
          {card.priority && (
            <span
              className={clsx(
                "rounded-md px-2 py-0.5 text-[11px] font-medium",
                PRIORITY_TONE[card.priority] ?? "bg-slate-100 text-slate-500",
              )}
            >
              {card.priority}
            </span>
          )}
        </div>
      </div>

      <div className="mt-1.5 font-semibold text-ink">{card.title}</div>
      {(card.flag || card.subtitle || card.score) && (
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <span className="truncate">
            {card.flag && <span className="mr-1">{card.flag}</span>}
            {card.subtitle}
          </span>
          {card.score && (
            <span className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600">
              {card.score}
            </span>
          )}
        </div>
      )}

      {card.amount != null && card.amount > 0 && (
        <div className="mt-1.5 font-semibold text-ink">{formatMoney(card.amount)}</div>
      )}

      {card.progress != null && (
        <div className="mt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand" style={{ width: `${card.progress}%` }} />
          </div>
          <div className="mt-1 text-[11px] text-muted">{card.progress}% готовности</div>
        </div>
      )}

      {/* AI-рекомендация по карточке (как в референсах закупок/производства) */}
      {card.insight && (
        <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-violet-50 px-2.5 py-1.5 text-[11px] text-violet-900">
          <Sparkles size={12} className="mt-0.5 shrink-0 text-violet-500" />
          <span>{card.insight}</span>
        </div>
      )}

      {card.next_step && (
        <div className="mt-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600">
          <span className="text-muted">След. шаг: </span>
          {card.next_step}
        </div>
      )}

      {/* Key-value блок (пересчёт склада / детали претензии) */}
      {card.details && card.details.length > 0 && (
        <div className="mt-2 space-y-1 rounded-lg bg-slate-50 px-2.5 py-2 text-[11px]">
          {card.details.map((d) => (
            <div key={d.k} className="flex justify-between gap-2">
              <span className="text-muted">{d.k}</span>
              <span className="font-medium text-ink">{d.v}</span>
            </div>
          ))}
        </div>
      )}

      {(card.tags.length > 0 || card.status_tag) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {card.status_tag && (
            <span className="rounded-md bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-600">
              {card.status_tag}
            </span>
          )}
          {card.tags.map((t) => (
            <span
              key={t}
              className={clsx(
                "rounded-md px-2 py-0.5 text-[11px] font-medium",
                CONTENT_TONE[t] ?? "bg-slate-100 font-normal text-slate-600",
              )}
            >
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Основная кнопка-действие карточки */}
      {card.action && (
        <button
          onClick={(e) => e.stopPropagation()}
          className="mt-2.5 w-full rounded-lg bg-blue-50 px-3 py-1.5 text-xs font-medium text-brand-600 hover:bg-blue-100"
        >
          {card.action}
        </button>
      )}

      {/* Пилюли «Фокус / Приоритет» */}
      {showFocusPills && (
        <div className="mt-2.5 flex gap-2">
          <span className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-200 py-1.5 text-xs font-medium text-slate-600">
            <Target size={13} className="text-brand-600" /> Фокус
          </span>
          <span className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-200 py-1.5 text-xs font-medium text-slate-600">
            <Flag size={13} className="text-amber-500" /> Приоритет
          </span>
        </div>
      )}

      {(card.owner || card.date) && (
        <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-slate-100 pt-2 text-xs text-muted">
          <span className="flex min-w-0 items-center gap-1.5">
            {card.owner && (
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-[9px] font-semibold text-white">
                {initials(card.owner)}
              </span>
            )}
            <span className="truncate">{card.owner}</span>
          </span>
          {card.date && <span className="shrink-0">{card.date}</span>}
        </div>
      )}

      {/* Мини-иконки действий (склад: документ/штрихкод/печать/фото) */}
      {showActions && (
        <div className="mt-2.5 flex items-center gap-2 border-t border-slate-100 pt-2.5">
          {ACTION_ICONS.map((Icon, i) => (
            <span key={i} className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-50 text-slate-500">
              <Icon size={14} />
            </span>
          ))}
        </div>
      )}

      {showChannels && (
        <div className="mt-2.5 flex items-center gap-2 border-t border-slate-100 pt-2.5">
          {CHANNELS.map(({ key, color, Icon }) => (
            <span
              key={key}
              className="flex h-6 w-6 items-center justify-center rounded-lg"
              style={{ backgroundColor: color + "14", color }}
            >
              <Icon size={13} />
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DraggableCard({
  card,
  onOpen,
  showChannels,
  showFocusPills,
  showActions,
}: {
  card: FunnelCard;
  onOpen?: () => void;
  showChannels?: boolean;
  showFocusPills?: boolean;
  showActions?: boolean;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: card.id });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={isDragging ? "opacity-40" : ""}>
      <Card
        card={card}
        onOpen={onOpen}
        showChannels={showChannels}
        showFocusPills={showFocusPills}
        showActions={showActions}
      />
    </div>
  );
}

function Column({
  stage,
  showSum,
  children,
}: {
  stage: FunnelStage;
  showSum: boolean;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-3">
      <div className="overflow-hidden rounded-xl bg-white shadow-card">
        <div className="h-1" style={{ backgroundColor: stage.color }} />
        <div className="px-4 py-3">
          <div className="font-semibold text-ink">{stage.title}</div>
          <div className="mt-0.5 text-xs text-muted">
            {stage.count} {stage.count === 1 ? "карточка" : "шт."}
            {showSum && stage.sum > 0 ? ` · ${formatMoney(stage.sum)}` : ""}
          </div>
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={clsx(
          "flex min-h-20 flex-col gap-3 rounded-xl p-1 transition-colors",
          isOver && "bg-brand-100/60 ring-2 ring-brand-100",
        )}
      >
        {children}
      </div>
    </div>
  );
}

function RightPanel({ panel }: { panel: FunnelPanel }) {
  return (
    <aside className="flex w-[300px] shrink-0 flex-col overflow-hidden border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3.5 font-semibold text-ink">{panel.title}</div>
      {panel.tabs && panel.tabs.length > 0 && (
        <div className="flex items-center gap-1 border-b border-slate-200 px-4 py-2">
          {panel.tabs.map((tab, i) => (
            <span
              key={tab}
              className={clsx(
                "rounded-md px-2.5 py-1 text-xs font-medium",
                i === 0 ? "bg-brand-100 text-brand-600" : "text-slate-500",
              )}
            >
              {tab}
            </span>
          ))}
        </div>
      )}
      <div className="flex-1 divide-y divide-slate-100 overflow-y-auto thin-scroll">
        {panel.items.map((it, i) => (
          <div key={i} className="px-4 py-3">
            <div className="flex items-center gap-2">
              <span className={clsx("h-2 w-2 shrink-0 rounded-full", PANEL_TONE[it.tone ?? "info"])} />
              <span className="flex-1 truncate text-sm font-medium text-ink">{it.title}</span>
              {it.badge ? (
                <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-semibold text-white">
                  {it.badge}
                </span>
              ) : null}
            </div>
            <p className="mt-0.5 pl-4 text-xs text-muted">{it.text}</p>
          </div>
        ))}
      </div>
    </aside>
  );
}

/** Таймлайн этапов: цепочка стадий воронки с отметкой пройденных/текущей/предстоящих. */
function StageTimeline({ stages, currentStageId }: { stages: FunnelStage[]; currentStageId: string }) {
  const curIdx = stages.findIndex((s) => s.id === currentStageId);
  return (
    <ol className="space-y-0">
      {stages.map((s, i) => {
        const done = i < curIdx;
        const current = i === curIdx;
        const last = i === stages.length - 1;
        return (
          <li key={s.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={clsx(
                  "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold",
                  done && "bg-emerald-500 text-white",
                  current && "bg-brand text-white",
                  !done && !current && "bg-slate-100 text-slate-400",
                )}
              >
                {done ? <Check size={13} /> : i + 1}
              </span>
              {!last && <span className={clsx("w-0.5 flex-1", done ? "bg-emerald-300" : "bg-slate-200")} style={{ minHeight: 18 }} />}
            </div>
            <div className={clsx("pb-3 text-sm", current ? "font-semibold text-ink" : "text-slate-500")}>
              {s.title}
              {current && <span className="ml-2 rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-medium text-brand-600">текущий этап</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function DetailDrawer({
  card,
  stageId,
  stages,
  extras,
  onClose,
}: {
  card: FunnelCard;
  stageId: string;
  stages: FunnelStage[];
  extras?: FunnelDetailExtras;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-pop thin-scroll"
      >
        <div className="flex items-start justify-between gap-2 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <div className="text-xs text-muted">Детали · № {card.code}</div>
            <h3 className="truncate text-lg font-bold text-ink">{card.title}</h3>
            {card.subtitle && <div className="text-sm text-muted">{card.subtitle}</div>}
          </div>
          <button onClick={onClose} className="shrink-0 text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-5 p-5">
          <div className="flex flex-wrap items-center gap-2">
            {card.priority && (
              <span className={clsx("rounded-md px-2 py-0.5 text-xs font-medium", PRIORITY_TONE[card.priority] ?? "bg-slate-100 text-slate-500")}>
                {card.priority}
              </span>
            )}
            {card.amount != null && card.amount > 0 && (
              <span className="text-sm font-semibold text-ink">{formatMoney(card.amount)}</span>
            )}
            {card.owner && <span className="text-sm text-muted">· {card.owner}</span>}
            {card.date && <span className="text-sm text-muted">· {card.date}</span>}
          </div>

          {card.progress != null && (
            <div>
              <div className="mb-1 flex justify-between text-xs text-muted">
                <span>Ход работ</span>
                <span>{card.progress}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-brand" style={{ width: `${card.progress}%` }} />
              </div>
            </div>
          )}

          {card.insight && (
            <div className="flex items-start gap-2 rounded-lg bg-violet-50 p-3 text-sm text-violet-900">
              <Sparkles size={15} className="mt-0.5 shrink-0 text-violet-500" />
              <span>{card.insight}</span>
            </div>
          )}

          {card.next_step && (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Следующий шаг</div>
              <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{card.next_step}</div>
            </div>
          )}

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Маршрут / этапы</div>
            <StageTimeline stages={stages} currentStageId={stageId} />
          </div>

          {extras?.operations && extras.operations.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">План / Факт по операциям</div>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr>
                    <th className="py-1 font-medium">Операция</th>
                    <th className="py-1 font-medium">План</th>
                    <th className="py-1 font-medium">Факт</th>
                    <th className="py-1 text-right font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {extras.operations.map((op) => (
                    <tr key={op.name} className="border-t border-slate-100">
                      <td className="py-1.5 text-ink">{op.name}</td>
                      <td className="py-1.5 text-slate-600">{op.plan}</td>
                      <td className="py-1.5 text-slate-600">{op.fact}</td>
                      <td
                        className={clsx(
                          "py-1.5 text-right font-medium",
                          op.status === "ok" ? "text-emerald-600" : op.status === "warn" ? "text-amber-600" : "text-red-600",
                        )}
                      >
                        {op.status === "ok" ? "OK" : op.status === "warn" ? "внимание" : "срыв"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {extras?.risk && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Прогноз риска</div>
              <div className="flex items-start gap-3">
                <div
                  className={clsx(
                    "text-2xl font-bold",
                    extras.risk.percent >= 60 ? "text-red-600" : extras.risk.percent >= 30 ? "text-amber-600" : "text-emerald-600",
                  )}
                >
                  {extras.risk.percent}%
                </div>
                <ul className="flex-1 space-y-1 text-xs text-slate-600">
                  {extras.risk.notes.map((n, i) => (
                    <li key={i} className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                      {n}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {extras?.bom && extras.bom.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Обеспеченность материалами (BOM)</div>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr>
                    <th className="py-1 font-medium">Компонент</th>
                    <th className="py-1 text-right font-medium">Нужно</th>
                    <th className="py-1 text-right font-medium">Склад</th>
                    <th className="py-1 text-right font-medium">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {extras.bom.map((b) => {
                    const ok = b.stock >= b.need;
                    return (
                      <tr key={b.name} className="border-t border-slate-100">
                        <td className="py-1.5 text-ink">{b.name}</td>
                        <td className="py-1.5 text-right text-slate-600">{b.need}</td>
                        <td className="py-1.5 text-right text-slate-600">{b.stock}</td>
                        <td className={clsx("py-1.5 text-right font-medium", ok ? "text-emerald-600" : "text-red-600")}>
                          {ok ? "OK" : `−${b.need - b.stock}`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {extras?.equipment && extras.equipment.length > 0 && (
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Загрузка оборудования</div>
              <div className="space-y-2">
                {extras.equipment.map((eq) => (
                  <div key={eq.name}>
                    <div className="mb-1 flex justify-between text-xs text-slate-600">
                      <span>{eq.name}</span>
                      <span>{eq.load}%</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                      <div
                        className={clsx("h-full rounded-full", eq.load > 85 ? "bg-red-500" : eq.load > 60 ? "bg-amber-500" : "bg-emerald-500")}
                        style={{ width: `${eq.load}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function FunnelBoard({
  title,
  subtitle,
  boardPath,
  createPath,
  patchPath,
  fields,
  createLabel = "Добавить",
  showSum = true,
  kpis,
  statusNote,
  insight,
  panel,
  summary,
  detailExtras,
  conversion,
  leaderboard,
  showChannels,
  showFocusPills,
  showActions,
  boardTabs,
}: FunnelBoardProps) {
  const [stages, setStages] = useState<FunnelStage[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Record<string, string | number>>(() => blankForm(fields));
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<FunnelCard | null>(null);
  const [selected, setSelected] = useState<{ card: FunnelCard; stageId: string } | null>(null);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  async function refresh() {
    setStages(await fetchFunnelBoard(boardPath));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardPath]);

  function handleDragStart(e: DragStartEvent) {
    const id = Number(e.active.id);
    setActive(stages.flatMap((s) => s.cards).find((c) => c.id === id) ?? null);
  }

  function handleDragEnd(e: DragEndEvent) {
    setActive(null);
    const id = Number(e.active.id);
    const target = e.over ? String(e.over.id) : null;
    if (!target) return;
    setStages((prev) => moveCard(prev, id, target));
    void moveFunnelCard(patchPath, id, target);
  }

  async function onCreate() {
    setBusy(true);
    await createFunnelCard(createPath, form);
    setBusy(false);
    setOpen(false);
    setForm(blankForm(fields));
    await refresh();
  }

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      stages.map((s) => ({
        ...s,
        cards: q
          ? s.cards.filter((c) =>
              `${c.code} ${c.title} ${c.subtitle} ${c.owner}`.toLowerCase().includes(q),
            )
          : s.cards,
      })),
    [stages, q],
  );

  const computed = useMemo(() => {
    const last = stages[stages.length - 1];
    let activeCount = 0;
    let activeSum = 0;
    let total = 0;
    for (const s of stages) {
      total += s.count;
      if (s.id !== last?.id) {
        activeCount += s.count;
        activeSum += s.sum;
      }
    }
    const doneCount = last?.count ?? 0;
    const metrics: FunnelSummaryMetric[] = [
      { label: "В работе", value: String(activeCount) },
      ...(showSum ? [{ label: "Сумма в работе", value: formatMoney(activeSum) }] : []),
      { label: "В финале", value: String(doneCount) },
      ...(showSum ? [{ label: "Сумма финала", value: formatMoney(last?.sum ?? 0) }] : []),
      { label: "Конверсия", value: `${total ? ((doneCount / total) * 100).toFixed(1) : "0.0"}%` },
    ];
    return metrics;
  }, [stages, showSum]);

  const summaryMetrics = summary ?? computed;

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        {/* Тулбар */}
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h1 className="text-xl font-bold text-ink">{title}</h1>
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          <div className="relative ml-auto min-w-[180px] max-w-xs flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск..."
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand"
            />
          </div>
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
            <SlidersHorizontal size={16} /> Фильтры
          </button>
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
            <Settings2 size={16} /> Настроить воронку
          </button>
          <button className="inline-flex items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 px-3.5 py-2 text-sm font-medium text-violet-600 hover:bg-violet-100">
            <Sparkles size={16} /> AI-ассистент
          </button>
          <button
            onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            <Plus size={16} /> {createLabel}
          </button>
        </div>

        {/* KPI «План/Факт» */}
        {kpis && kpis.length > 0 && (
          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {kpis.map((k) => (
              <KpiTile key={k.label} kpi={k} />
            ))}
          </div>
        )}

        {/* AI-инсайт */}
        {insight && (
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-indigo-100 bg-indigo-50/50 p-3 text-sm text-slate-700">
            <Sparkles size={16} className="mt-0.5 shrink-0 text-indigo-500" />
            <span>
              <span className="font-semibold text-indigo-600">AI-инсайт: </span>
              {insight}
            </span>
          </div>
        )}

        {/* Форма создания */}
        {open && (
          <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-white p-4 shadow-card">
            {fields.map((f) => (
              <label key={f.key} className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">{f.label}</span>
                <input
                  type={f.type ?? "text"}
                  value={form[f.key]}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value,
                    })
                  }
                  className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
                />
              </label>
            ))}
            <button
              onClick={onCreate}
              disabled={busy}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            >
              Сохранить
            </button>
          </div>
        )}

        {/* Табы над доской + переключатель вида (база знаний) */}
        {boardTabs && boardTabs.length > 0 && (
          <div className="mt-4 flex items-center justify-between">
            <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5">
              {boardTabs.map((tab, i) => (
                <span
                  key={tab}
                  className={clsx(
                    "rounded-md px-3 py-1 text-xs font-medium",
                    i === 0 ? "bg-brand-100 text-brand-600" : "text-slate-500",
                  )}
                >
                  {tab}
                </span>
              ))}
            </div>
            <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5">
              <span className="rounded-md bg-brand-100 p-1.5 text-brand-600">
                <LayoutGrid size={14} />
              </span>
              <span className="p-1.5 text-slate-400">
                <List size={14} />
              </span>
            </div>
          </div>
        )}

        {/* Статус-бар над воронкой */}
        <div className="mt-5 flex items-center gap-2 text-xs text-muted">
          {statusNote ? <span>{statusNote}</span> : <span>Перетащите карточку, чтобы сменить стадию.</span>}
        </div>

        {/* Канбан */}
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="mt-2 flex gap-4 overflow-x-auto pb-2 thin-scroll">
            {filtered.map((stage) => (
              <Column key={stage.id} stage={stage} showSum={showSum}>
                {stage.cards.map((card) => (
                  <DraggableCard
                    key={card.id}
                    card={card}
                    showChannels={showChannels}
                    showFocusPills={showFocusPills}
                    showActions={showActions}
                    onOpen={() => setSelected({ card, stageId: stage.id })}
                  />
                ))}
              </Column>
            ))}
            {filtered.length === 0 && <p className="p-6 text-sm text-muted">Загрузка доски…</p>}
          </div>
          <DragOverlay>
            {active ? (
              <div className="w-[280px] rotate-2">
                <Card card={active} showChannels={showChannels} showFocusPills={showFocusPills} showActions={showActions} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>

        {/* Итоги */}
        <div className="mt-4 rounded-xl bg-white p-5 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-ink">Итоги по воронке</h3>
            <span className="text-xs text-muted">за период</span>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {summaryMetrics.map((m) => (
              <div key={m.label}>
                <div className="text-xs text-muted">{m.label}</div>
                <div className="mt-1 text-2xl font-bold text-ink">{m.value}</div>
                {m.delta && (
                  <div
                    className={clsx(
                      "text-xs font-medium",
                      m.delta.trim().startsWith("−") || m.delta.trim().startsWith("-")
                        ? "text-red-600"
                        : "text-emerald-600",
                    )}
                  >
                    {m.delta}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Конверсия по воронке (реальные счётчики стадий) */}
        {conversion && stages.length > 0 && (
          <div className="mt-4 rounded-xl bg-white p-5 shadow-card">
            <h3 className="mb-4 font-semibold text-ink">Конверсия по воронке</h3>
            <div className="space-y-2">
              {stages.map((s) => {
                const first = stages[0]?.count || 1;
                const pct = Math.round((s.count / first) * 100);
                return (
                  <div key={s.id} className="flex items-center gap-3">
                    <span className="w-40 shrink-0 truncate text-sm text-ink">{s.title}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: s.color }} />
                    </div>
                    <span className="w-24 shrink-0 text-right text-sm text-muted">
                      {s.count} · {pct}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Лидерборд (топ-рекрутёры) */}
        {leaderboard && leaderboard.length > 0 && (
          <div className="mt-4 rounded-xl bg-white p-5 shadow-card">
            <h3 className="mb-4 font-semibold text-ink">Топ рекрутёры</h3>
            <div className="space-y-3">
              {leaderboard.map((r, i) => (
                <div key={r.name} className="flex items-center gap-3">
                  <span className="w-5 shrink-0 text-sm font-semibold text-muted">{i + 1}</span>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 text-[10px] font-semibold text-white">
                    {initials(r.name)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">{r.name}</div>
                    <div className="truncate text-xs text-muted">{r.meta}</div>
                  </div>
                  <span className="shrink-0 text-sm font-semibold text-ink">{r.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {panel && <RightPanel panel={panel} />}

      {selected && (
        <DetailDrawer
          card={selected.card}
          stageId={selected.stageId}
          stages={stages}
          extras={detailExtras}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
