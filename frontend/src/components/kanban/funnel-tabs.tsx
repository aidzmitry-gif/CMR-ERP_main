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
    <div className="flex items-center gap-1">
      {funnels.map((f) => {
        const isActive = f.code === current;
        return (
          <button
            key={f.code}
            onClick={() => switchTo(f.code)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
              isActive
                ? "border-accent bg-accent-soft text-accent-ink"
                : "border-line bg-surface text-muted hover:bg-sunken"
            }`}
          >
            {f.title}
            <span className="rounded px-1 py-0.5 text-[10px] tabular-nums text-muted">
              {f.active_deals}
            </span>
          </button>
        );
      })}
    </div>
  );
}
