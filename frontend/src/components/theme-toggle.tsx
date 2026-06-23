"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * Переключатель тем C (светлая) ⇄ D (тёмная).
 * Меняет класс .dark на <html> и пишет выбор в localStorage("theme").
 * Начальное состояние ставит THEME_INIT_SCRIPT в <head> (без мигания) — здесь только синхронизируемся.
 */
export function ThemeToggle() {
  // initial=false совпадает с SSR (там нет document) — иначе гидрация падает
  // (сервер рисует Moon, клиент с .dark — Sun). Фактическую тему читаем после маунта.
  const [dark, setDark] = useState(false);
  useEffect(() => {
    // queueMicrotask — чтобы не вызывать setState синхронно в теле эффекта (идиома проекта)
    queueMicrotask(() => setDark(document.documentElement.classList.contains("dark")));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* приватный режим — просто не сохраняем */
    }
  }

  return (
    <button
      onClick={toggle}
      title={dark ? "Светлая тема" : "Тёмная тема"}
      aria-label={dark ? "Включить светлую тему" : "Включить тёмную тему"}
      className="flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken"
    >
      {dark ? <Sun size={19} /> : <Moon size={19} />}
    </button>
  );
}

/**
 * Инлайн-скрипт, исполняемый ДО первого рендера (в <head> через next/script strategy=beforeInteractive
 * или dangerouslySetInnerHTML). Ставит .dark ТОЛЬКО если в localStorage сохранён выбор «dark» —
 * по умолчанию приложение светлое (курс DESIGN.md, Stripe/Notion), тёмная включается тумблером.
 * Без вспышки светлого при загрузке сохранённой тёмной.
 */
export const THEME_INIT_SCRIPT = `(function(){try{document.documentElement.classList.toggle('dark',localStorage.getItem('theme')==='dark');}catch(e){}})();`;
