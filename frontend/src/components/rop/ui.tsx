import clsx from "clsx";
import type { ReactNode } from "react";

import type { Tone } from "@/lib/rop-data";

/** Палитры тонов для тегов, баров, текста и левой границы карточек. */
export const TAG_TONE: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-700",
  amber: "bg-amber-50 text-amber-700",
  red: "bg-red-50 text-red-600",
  blue: "bg-brand-100 text-brand-600",
  violet: "bg-violet-50 text-violet-600",
  slate: "bg-slate-100 text-slate-600",
  teal: "bg-teal-50 text-teal-700",
};

export const BAR_TONE: Record<Tone, string> = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-red-500",
  blue: "bg-brand",
  violet: "bg-violet-500",
  slate: "bg-slate-400",
  teal: "bg-teal-500",
};

export const TEXT_TONE: Record<Tone, string> = {
  green: "text-emerald-600",
  amber: "text-amber-600",
  red: "text-red-600",
  blue: "text-brand-600",
  violet: "text-violet-600",
  slate: "text-slate-500",
  teal: "text-teal-600",
};

export const BORDER_TONE: Record<Tone, string> = {
  green: "border-emerald-400",
  amber: "border-amber-400",
  red: "border-red-400",
  blue: "border-brand",
  violet: "border-violet-400",
  slate: "border-slate-300",
  teal: "border-teal-400",
};

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section className={clsx("rounded-2xl bg-white p-5 shadow-card", className)}>{children}</section>
  );
}

export function Caption({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("text-[11px] font-semibold uppercase tracking-wide text-slate-400", className)}>
      {children}
    </div>
  );
}

export function Tag({ tone = "slate", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
        TAG_TONE[tone],
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone }: { tone: Tone }) {
  return <span className={clsx("h-2 w-2 shrink-0 rounded-full", BAR_TONE[tone])} />;
}

export function Avatar({ name }: { name: string }) {
  const letter = name.trim()[0]?.toUpperCase() ?? "?";
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-600">
      {letter}
    </span>
  );
}

export function Bar({ percent, tone = "blue", className }: { percent: number; tone?: Tone; className?: string }) {
  return (
    <div className={clsx("h-2 w-full overflow-hidden rounded-full bg-slate-100", className)}>
      <div
        className={clsx("h-full rounded-full", BAR_TONE[tone])}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  );
}
