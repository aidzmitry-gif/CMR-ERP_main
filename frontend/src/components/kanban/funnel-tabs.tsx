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

  // Скрываем все «технические» состояния — пока воронки не пришли, доска работает на
  // дефолтной (new_clients из канона). Шум типа «Воронки не настроены» больше не лезет
  // в макет, только когда бэк уверенно прислал ≥2 воронки — рисуем таб.
  if (status === "loading" || status === "error") return null;
  if (funnels.length <= 1) return null;
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
