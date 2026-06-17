"use client";

import clsx from "clsx";

import type { Grade } from "@/lib/logistics-domain";

/** Карточка-секция с белым фоном и необязательной шапкой/действием. */
export function Card({
  title,
  hint,
  action,
  children,
  className,
}: {
  title?: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("rounded-xl bg-surface p-5 shadow-card", className)}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            {title && <h3 className="font-semibold text-ink">{title}</h3>}
            {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

/** Плитка KPI: подпись + крупное значение + примечание. */
export function KpiTile({
  label,
  value,
  sub,
  tone = "ink",
}: {
  label: string;
  value: string | number;
  sub?: string;
  tone?: "ink" | "emerald" | "amber" | "red" | "brand";
}) {
  const toneCls = {
    ink: "text-ink",
    emerald: "text-emerald-600",
    amber: "text-amber-600",
    red: "text-red-600",
    brand: "text-accent-ink",
  }[tone];
  return (
    <div className="rounded-xl bg-surface p-4 shadow-card">
      <div className="text-[11px] leading-tight text-muted">{label}</div>
      <div className={clsx("mt-1 text-xl font-bold tabular-nums", toneCls)}>{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-faint">{sub}</div>}
    </div>
  );
}

/** Пустое состояние с необязательной кнопкой засева демо-данных. */
export function EmptyState({
  text,
  onSeed,
  seedLabel = "Заполнить демо-данными",
  busy,
}: {
  text: string;
  onSeed?: () => void;
  seedLabel?: string;
  busy?: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl bg-surface p-10 text-center shadow-card">
      <p className="text-sm text-muted">{text}</p>
      {onSeed && (
        <button
          onClick={onSeed}
          disabled={busy}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          {busy ? "Заполняем…" : seedLabel}
        </button>
      )}
    </div>
  );
}

/** Индикатор загрузки секции. */
export function Loading() {
  return <p className="rounded-xl bg-surface p-10 text-center text-sm text-muted shadow-card">Загрузка…</p>;
}

/** Бейдж грейда перевозчика A/B/C с цветом. */
export function GradeBadge({ grade }: { grade: Grade | string }) {
  const tone =
    grade === "A"
      ? "bg-emerald-50 text-emerald-600"
      : grade === "B"
        ? "bg-amber-50 text-amber-600"
        : "bg-red-50 text-red-600";
  return (
    <span className={clsx("inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold", tone)}>
      {grade}
    </span>
  );
}

/** Небольшая статус-пилюля. */
export function Pill({ text, tone = "slate" }: { text: string; tone?: "slate" | "blue" | "emerald" | "amber" | "violet" }) {
  const cls = {
    slate: "bg-sunken text-muted",
    blue: "bg-blue-50 text-blue-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    violet: "bg-violet-50 text-violet-600",
  }[tone];
  return <span className={clsx("rounded-md px-2 py-0.5 text-[11px] font-medium", cls)}>{text}</span>;
}

/** Кнопка вторичного действия (тулбар секции). */
export function GhostButton({
  onClick,
  children,
  busy,
}: {
  onClick: () => void;
  children: React.ReactNode;
  busy?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
    >
      {children}
    </button>
  );
}
