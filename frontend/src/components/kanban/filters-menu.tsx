"use client";

import { SlidersHorizontal } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

const PRIORITIES = ["Высокий", "Средний", "Низкий"];

/**
 * Фильтр по приоритету сделки — живёт в шапке страницы (правее переключателя ЮЛ, решение
 * оператора), доска же — отдельное поддерево React (children AppShell). Выбор — через URL
 * (`?priority=…`), тот же паттерн, что у {@link FunnelTabs} для `?funnel=…`: DealsWorkspace
 * читает `useSearchParams()` напрямую, без прокидывания пропсов между несвязанными деревьями.
 */
export function FiltersMenu() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);
  const priority = params.get("priority");

  function setPriority(p: string | null) {
    const next = new URLSearchParams(params.toString());
    if (p) next.set("priority", p);
    else next.delete("priority");
    router.replace(`${pathname}?${next.toString()}`);
    setOpen(false);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken ${
          priority || open ? "border-accent text-accent-ink" : "border-line text-muted"
        }`}
      >
        <SlidersHorizontal size={16} /> Фильтры
        {priority && (
          <span className="rounded bg-accent-soft px-1.5 text-xs text-accent-ink">{priority}</span>
        )}
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="Закрыть"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-20 mt-1 w-48 rounded-xl border border-line bg-surface p-1 shadow-pop">
            <div className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
              Приоритет
            </div>
            {[null, ...PRIORITIES].map((p) => (
              <button
                key={p ?? "all"}
                type="button"
                onClick={() => setPriority(p)}
                className={`block w-full rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-sunken ${
                  priority === p ? "font-semibold text-accent-ink" : "text-muted"
                }`}
              >
                {p ?? "Все"}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
