"use client";

import Link from "next/link";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Group = "accounting" | "goods" | "submission";
type Item = { id: string; title: string; group: Group; note: string; href?: string; tab?: string; anchor?: string };
export type ReportFavoriteState = { ids: string[]; loaded: boolean };

const storageKey = "accountant-report-favorites-v1";
const groups: { id: Group | "favorites"; title: string }[] = [
  { id: "accounting", title: "Бухгалтерские" },
  { id: "goods", title: "Товары и расчёты" },
  { id: "submission", title: "Для сдачи" },
  { id: "favorites", title: "Избранное" },
];
const items: Item[] = [
  { id: "trial", title: "ОСВ", group: "accounting", note: "Оборотно-сальдовая ведомость выбранного юрлица и периода", anchor: "accounting-trial-balance" },
  { id: "card", title: "Карточка и анализ счёта", group: "accounting", note: "Выберите строку счёта в ОСВ", anchor: "accounting-trial-balance" },
  { id: "journal", title: "Журнал проводок", group: "accounting", note: "Операции выбранного периода", anchor: "accounting-journal" },
  { id: "pnl", title: "Прибыль и убытки", group: "accounting", note: "Финансовый отчёт; юрлицо и период выбираются на открывшейся странице", href: "/erp/finance?tab=pnl" },
  { id: "dds", title: "Движение денег", group: "accounting", note: "Финансовый отчёт; юрлицо и период выбираются на открывшейся странице", href: "/erp/finance?tab=dds" },
  { id: "balance", title: "Баланс", group: "accounting", note: "Финансовый отчёт; юрлицо и период выбираются на открывшейся странице", href: "/erp/finance?tab=balance" },
  { id: "reconciliation", title: "Сверка ОСВ", group: "goods", note: "Рабочая сверка бухгалтерской книги", tab: "reconciliation" },
  { id: "settlements", title: "Оплаты и зачёты счетов", group: "goods", note: "Операционный экран, не отчёт о задолженности", tab: "invoice-settlements" },
  { id: "stock", title: "Остатки на складе", group: "goods", note: "Физические остатки WMS; стоимость проверяйте по ОСВ", href: "/erp/wms/stock" },
  { id: "expenses", title: "Контроль расходов", group: "goods", note: "Рабочий экран статей и расходов", tab: "expenses" },
  { id: "debts", title: "Дебиторская и кредиторская задолженность", group: "goods", note: "Документный отчёт ещё не реализован" },
  { id: "acts", title: "Акты сверки с контрагентами", group: "goods", note: "Печатный отчёт ещё не реализован" },
  { id: "lots", title: "Себестоимость партий", group: "goods", note: "Отчёт с распределением дополнительных расходов ещё не реализован" },
  { id: "margin", title: "Валовая прибыль по товарам", group: "goods", note: "Отчёт по фактической себестоимости и возвратам ещё не реализован" },
  { id: "turnover", title: "Оборачиваемость товаров", group: "goods", note: "Отчёт ещё не реализован" },
  { id: "calendar", title: "Платёжный календарь", group: "goods", note: "Отчёт план/факт ещё не реализован" },
  { id: "requirements", title: "Применимость форм и ставок", group: "submission", note: "Рабочий реестр требований; не готовая декларация", tab: "statutory-requirements" },
  { id: "vat", title: "Декларация по НДС", group: "submission", note: "Формирование и отправка не реализованы" },
  { id: "profit-tax", title: "Декларация по налогу на прибыль", group: "submission", note: "Формирование и отправка не реализованы" },
  { id: "income-tax", title: "Декларация налогового агента", group: "submission", note: "Формирование и отправка не реализованы" },
  { id: "eaeu-vat", title: "НДС при ввозе из ЕАЭС", group: "submission", note: "Формирование и отправка не реализованы" },
  { id: "four-fund", title: "4-фонд", group: "submission", note: "Формирование и отправка не реализованы" },
];

export function AccountingReportCatalog({ onOpen, reportReady, favoriteState, setFavoriteState }: { onOpen: (tab: string) => void; reportReady: boolean; favoriteState: ReportFavoriteState; setFavoriteState: Dispatch<SetStateAction<ReportFavoriteState>> }) {
  const [group, setGroup] = useState<Group | "favorites">("accounting");
  const [query, setQuery] = useState("");
  const favorites = favoriteState.ids;

  useEffect(() => {
    if (favoriteState.loaded) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      let storedIds: string[] | null = null;
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey) ?? "[]") as unknown;
        if (Array.isArray(stored)) storedIds = stored.filter((id): id is string => typeof id === "string" && items.some((item) => item.id === id));
      } catch { /* Favorites still work in memory when browser storage is unavailable. */ }
      setFavoriteState((current) => current.loaded ? current : { ids: storedIds ?? current.ids, loaded: true });
    });
    return () => { active = false; };
  }, [favoriteState.loaded, setFavoriteState]);

  function toggleFavorite(id: string) {
    const next = favorites.includes(id) ? favorites.filter((value) => value !== id) : [...favorites, id];
    setFavoriteState({ ids: next, loaded: true });
    try { localStorage.setItem(storageKey, JSON.stringify(next)); } catch { /* Keep the in-memory choice. */ }
  }

  const visible = items.filter((item) => (group === "favorites" ? favorites.includes(item.id) : item.group === group)
    && item.title.toLocaleLowerCase("ru").includes(query.trim().toLocaleLowerCase("ru")));

  return <section aria-label="Каталог отчётов" className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <div><h2 className="font-semibold">Каталог отчётов</h2><p className="text-sm text-muted">Доступные экраны используют данные ERP. Неподготовленные отчёты и внешняя отправка здесь не открываются.</p></div>
    <nav aria-label="Группы отчётов" className="flex flex-wrap gap-2">{groups.map((row) =>
      <Button key={row.id} variant={group === row.id ? "primary" : "secondary"} aria-pressed={group === row.id} onClick={() => setGroup(row.id)}>{row.title}</Button>
    )}</nav>
    <Input aria-label="Поиск отчёта" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по названию" />
    <div className="grid gap-2 md:grid-cols-2">{visible.map((item) => <article key={item.id} className="rounded-lg border border-line p-3">
      <div className="flex items-start justify-between gap-2"><h3 className="font-medium">{item.title}</h3><button type="button" aria-label={`${favorites.includes(item.id) ? "Убрать из избранного" : "В избранное"}: ${item.title}`} aria-pressed={favorites.includes(item.id)} onClick={() => toggleFavorite(item.id)} className="shrink-0 text-accent underline">{favorites.includes(item.id) ? "★" : "☆"}</button></div>
      <p className="mt-1 text-sm text-muted">{item.note}</p>
      <div className="mt-2 text-sm">{item.href ? <Link className="text-accent underline" href={item.href}>Открыть</Link>
        : item.anchor ? reportReady ? <a className="text-accent underline" href={`#${item.anchor}`}>Открыть</a> : <span className="text-muted">Дождитесь загрузки книги</span>
        : item.tab ? <button className="text-accent underline" onClick={() => { if (item.tab) onOpen(item.tab); }}>Открыть</button>
        : <span className="text-muted">Пока недоступен</span>}</div>
    </article>)}</div>
    {!visible.length && <p className="text-sm text-muted">{group === "favorites" && !favorites.length ? "Закрепите нужные отчёты звёздочкой." : "По вашему запросу отчёты не найдены."}</p>}
  </section>;
}
