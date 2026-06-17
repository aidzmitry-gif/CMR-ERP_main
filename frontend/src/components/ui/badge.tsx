import { type HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export type BadgeTone = "emerald" | "teal" | "amber" | "red" | "violet" | "accent" | "slate";

const tones: Record<BadgeTone, string> = {
  emerald: "bg-[#E6F4EA] text-[#0F9D58]",
  teal: "bg-[#E4F5F2] text-[#0E9384]",
  amber: "bg-[#FCF1DD] text-[#B45309]",
  red: "bg-[#FCEAEA] text-[#DC2626]",
  violet: "bg-[#F2EBFE] text-[#7C3AED]",
  accent: "bg-accent-soft text-accent-ink",
  slate: "bg-sunken text-muted",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

/**
 * Бейдж/чип статуса. Единый размер (text-[11px], pill) — см. frontend/DESIGN.md.
 * Тон по смыслу: emerald=успех/факт, teal=прогноз, amber=внимание, red=ошибка, violet=AI.
 */
export function Badge({ tone = "slate", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
