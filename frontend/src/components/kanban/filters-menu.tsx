"use client";

import { SlidersHorizontal } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchManagersCached } from "@/components/kanban/deal-card";
import type { Manager } from "@/lib/types";

const PRIORITIES = ["Высокий", "Средний", "Низкий"];

/** Фильтры «Внимание»: горящие срезы доски (?attn=). Ключи читает DealsWorkspace. */
const ATTENTION = [
  { key: "overdue", label: "Просроченные" },
  { key: "no_step", label: "Без шага" },
  { key: "revive", label: "Реанимировать" },
];

function Section({ title }: { title: string }) {
  return (
    <div className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
      {title}
    </div>
  );
}

function Item({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`block w-full rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-sunken ${
        selected ? "font-semibold text-accent-ink" : "text-muted"
      }`}
    >
      {label}
    </button>
  );
}

/**
 * Фильтры доски — живут в шапке страницы (правее переключателя ЮЛ, решение оператора),
 * доска же — отдельное поддерево React (children AppShell). Выбор — через URL
 * (`?priority=…`, `?owner=…`, `?attn=…`), тот же паттерн, что у {@link FunnelTabs} для
 * `?funnel=…`: DealsWorkspace читает `useSearchParams()` напрямую, без прокидывания
 * пропсов между несвязанными деревьями. Активные фильтры видны бейджами на кнопке.
 */
export function FiltersMenu() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);
  // Список менеджеров для секции «Ответственный» — грузим один раз при первом открытии.
  const [managers, setManagers] = useState<Manager[] | null>(null);
  const priority = params.get("priority");
  const owner = params.get("owner");
  const attn = params.get("attn");
  const attnLabel = ATTENTION.find((a) => a.key === attn)?.label;

  useEffect(() => {
    if (open && managers == null) {
      // Общий кэш с меню карточки и «Чья доска» — реальный fetch случается один раз.
      void fetchManagersCached().then(setManagers);
    }
  }, [open, managers]);

  function setParam(key: "priority" | "owner" | "attn", value: string | null) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}?${next.toString()}`);
    setOpen(false);
  }

  const active = priority || owner || attn;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken ${
          active || open ? "border-accent text-accent-ink" : "border-line text-muted"
        }`}
      >
        <SlidersHorizontal size={16} /> Фильтры
        {priority && (
          <span className="rounded bg-accent-soft px-1.5 text-xs text-accent-ink">{priority}</span>
        )}
        {owner && (
          <span className="rounded bg-accent-soft px-1.5 text-xs text-accent-ink">{owner}</span>
        )}
        {attnLabel && (
          <span className="rounded bg-amber-100 px-1.5 text-xs font-semibold text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
            {attnLabel}
          </span>
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
          <div className="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-line bg-surface p-1 shadow-pop">
            <Section title="Приоритет" />
            {[null, ...PRIORITIES].map((p) => (
              <Item
                key={p ?? "all"}
                label={p ?? "Все"}
                selected={priority === p}
                onClick={() => setParam("priority", p)}
              />
            ))}
            <div className="my-1 border-t border-line" />
            <Section title="Ответственный" />
            <Item label="Все" selected={owner == null} onClick={() => setParam("owner", null)} />
            <div className="max-h-44 overflow-y-auto">
              {managers == null ? (
                <div className="px-2.5 py-1.5 text-xs text-faint">Загрузка…</div>
              ) : managers.length === 0 ? (
                <div className="px-2.5 py-1.5 text-xs text-faint">Список недоступен</div>
              ) : (
                managers.map((m) => (
                  <Item
                    key={m.name}
                    label={m.name}
                    selected={owner === m.name}
                    onClick={() => setParam("owner", m.name)}
                  />
                ))
              )}
            </div>
            <div className="my-1 border-t border-line" />
            <Section title="Внимание" />
            <Item label="Все" selected={attn == null} onClick={() => setParam("attn", null)} />
            {ATTENTION.map((a) => (
              <Item
                key={a.key}
                label={a.label}
                selected={attn === a.key}
                onClick={() => setParam("attn", a.key)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
