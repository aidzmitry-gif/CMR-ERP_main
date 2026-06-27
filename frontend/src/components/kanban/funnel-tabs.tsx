"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { fetchFunnels, type FunnelRow } from "@/lib/api";

/**
 * Таб-переключатель воронок над доской (мульти-воронки, ТЗ п.5).
 *
 * Данные — `/sales/funnels`. Выбор живёт в URL (`?funnel=…`) для шаринга/SSR — смена
 * вкладки делает `router.replace`, родительская SSR-страница перезагружает колонки
 * `/board?funnel=…`. Состояния: загрузка (плейсхолдеры), ошибка+повтор, honest-empty
 * (фасад вернул [] — нет воронок: до материализации канона или невалидный код).
 *
 * Скрывается, если всего одна воронка — не плодим шум.
 */
type Status = "loading" | "error" | "ready";

export function FunnelTabs({ active }: { active?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [status, setStatus] = useState<Status>("loading");
  const [funnels, setFunnels] = useState<FunnelRow[]>([]);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const rows = await fetchFunnels();
      setFunnels(rows);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function switchTo(code: string) {
    const next = new URLSearchParams(params.toString());
    next.set("funnel", code);
    router.replace(`${pathname}?${next.toString()}`);
  }

  if (status === "loading") {
    return (
      <div className="mb-3 flex gap-2">
        {[1, 2].map((i) => (
          <span key={i} className="h-7 w-32 animate-pulse rounded-md bg-sunken" />
        ))}
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[12.5px] text-muted">Не удалось загрузить воронки.</span>
        <button onClick={() => void load()} className="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white">
          Повторить
        </button>
      </div>
    );
  }
  if (funnels.length === 0) {
    return (
      <div className="mb-3 text-[12.5px] text-muted">
        Воронки не настроены — выполните миграцию или зайдите в редактор стадий.
      </div>
    );
  }
  if (funnels.length === 1) return null;
  const current = active ?? funnels[0].code;
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1 border-b border-line">
      {funnels.map((f) => {
        const isActive = f.code === current;
        return (
          <button
            key={f.code}
            onClick={() => switchTo(f.code)}
            className={`relative px-3 py-1.5 text-sm ${
              isActive ? "font-semibold text-accent-ink" : "text-muted hover:text-ink"
            }`}
          >
            {f.title}
            <span className="ml-1.5 rounded bg-sunken px-1.5 py-0.5 text-[10px] tabular-nums text-muted">
              {f.active_deals}
            </span>
            {isActive && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-accent" />}
          </button>
        );
      })}
    </div>
  );
}
