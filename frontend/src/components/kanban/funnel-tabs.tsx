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
  // в макет, только когда бэк уверенно прислал ≥2 воронки — рисуем выбор (и «Все вместе»).
  if (status === "loading" || status === "error") return null;
  if (funnels.length <= 1) return null;
  const current = active ?? funnels[0].code;
  return (
    <select
      aria-label="Воронка"
      value={current}
      onChange={(e) => switchTo(e.target.value)}
      className={`rounded-lg border px-3 py-2 text-sm font-medium outline-none ${
        current === "all"
          ? "border-accent bg-accent-soft text-accent-ink"
          : "border-line bg-surface text-ink"
      }`}
    >
      <option value="all">▦ Все вместе</option>
      {funnels.map((f) => (
        <option key={f.code} value={f.code}>
          {f.title} · {f.active_deals}
        </option>
      ))}
    </select>
  );
}
