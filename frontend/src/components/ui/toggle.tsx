"use client";

import { type InputHTMLAttributes, type ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";

/** Чекбокс с подписью. Управляемый/неуправляемый — как обычный input. */
export function Checkbox({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-sm", className)}>
      <span className="relative inline-flex size-[18px] items-center justify-center">
        <input type="checkbox" className="peer absolute inset-0 cursor-pointer opacity-0" {...props} />
        <span className="size-[18px] rounded-md border-2 border-line-strong transition-colors peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:ring-[3px] peer-focus-visible:ring-accent/30" />
        <Check className="pointer-events-none absolute size-3 text-white opacity-0 peer-checked:opacity-100" />
      </span>
      {label && <span className="select-none text-ink">{label}</span>}
    </label>
  );
}

/** Переключатель (switch). */
export function Switch({ label, className, ...props }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2.5 text-sm", className)}>
      <span className="relative inline-flex h-[22px] w-[38px] items-center">
        <input type="checkbox" className="peer absolute inset-0 cursor-pointer opacity-0" {...props} />
        <span className="h-[22px] w-[38px] rounded-full bg-[#D8D8DF] transition-colors peer-checked:bg-accent peer-focus-visible:ring-[3px] peer-focus-visible:ring-accent/30" />
        <span className="pointer-events-none absolute left-0.5 size-[18px] rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
      </span>
      {label && <span className="select-none text-ink">{label}</span>}
    </label>
  );
}
