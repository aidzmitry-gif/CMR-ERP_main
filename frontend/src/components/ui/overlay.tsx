"use client";

import { type ReactNode, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

/** Вкладки (pill-tabs, как в кокпите РОП). */
export function Tabs({ tabs, initial = 0 }: { tabs: { label: string; content?: ReactNode }[]; initial?: number }) {
  const [active, setActive] = useState(initial);
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {tabs.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setActive(i)}
            className={cn(
              "rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors",
              i === active ? "bg-accent text-white shadow-card" : "bg-surface text-muted shadow-card hover:text-accent-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs[active]?.content && <div className="mt-4">{tabs[active].content}</div>}
    </div>
  );
}

/** Модальное окно по центру. */
export function Modal({ open, onClose, title, children, footer }: {
  open: boolean; onClose: () => void; title?: string; children: ReactNode; footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-[#0f172a]/40" />
      <div
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <span className="text-[15px] font-bold">{title}</span>
          <button onClick={onClose} className="ml-auto rounded-md p-1 text-faint hover:bg-sunken hover:text-ink"><X className="size-4" /></button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-line bg-sunken px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  );
}

/** Drawer справа (для карточки-сделки и т.п.). */
export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: string; children: ReactNode }) {
  return (
    <div className={cn("fixed inset-0 z-50", open ? "" : "pointer-events-none")}>
      <div className={cn("absolute inset-0 bg-[#0f172a]/40 transition-opacity", open ? "opacity-100" : "opacity-0")} onClick={onClose} />
      <div
        className={cn(
          "absolute right-0 top-0 flex h-full w-[460px] max-w-[94vw] flex-col border-l border-line bg-surface shadow-pop transition-transform",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <span className="text-[15px] font-bold">{title}</span>
          <button onClick={onClose} className="ml-auto rounded-md p-1 text-faint hover:bg-sunken hover:text-ink"><X className="size-4" /></button>
        </div>
        <div className="flex-1 overflow-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

/** Тултип на CSS-hover (без зависимостей). */
export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#1A1A23] px-2 py-1 text-[11px] font-medium text-white opacity-0 transition-opacity group-hover:opacity-100">
        {text}
      </span>
    </span>
  );
}
