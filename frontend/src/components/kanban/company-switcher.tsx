"use client";

import { Check, ChevronDown, Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { useCurrency } from "./currency-context";

/**
 * Переключатель юр-лица (контур раздельного учёта) — порт co-pick из
 * sales-board-mockup.html. Смена ЮЛ меняет базовую валюту всех сумм доски.
 * «Глазок» прячет ЮЛ из быстрого списка (UI-фильтр, не право; текущее не скрыть).
 */
export function CompanySwitcher() {
  const { company, companies, setCompany } = useCurrency();
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const visible = companies.filter((c) => c.id === company.id || !hidden.has(c.id));

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Юридическое лицо · контур раздельного учёта"
        className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-sunken"
      >
        <span aria-hidden>{company.flag}</span>
        <span className="max-w-[150px] truncate">{company.name}</span>
        <span className="rounded bg-sunken px-1.5 py-0.5 text-[11px] font-semibold text-muted">
          {company.base}
        </span>
        <ChevronDown size={14} className="text-faint" />
      </button>

      {open && (
        <>
          <button
            type="button"
            aria-label="Закрыть"
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 z-20 mt-1 w-72 rounded-xl border border-line bg-surface p-1 shadow-pop">
            <div className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
              Юр-лицо · раздельный учёт
            </div>
            {visible.map((c) => {
              const cur = c.id === company.id;
              const hid = hidden.has(c.id);
              return (
                <div key={c.id} className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setCompany(c.id);
                      setOpen(false);
                    }}
                    className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-sunken ${
                      cur ? "font-semibold text-ink" : "text-muted"
                    }`}
                  >
                    <span aria-hidden>{c.flag}</span>
                    <span className="min-w-0 flex-1 truncate">{c.name}</span>
                    <span className="shrink-0 text-[11px] text-faint">{c.base}</span>
                    {cur && <Check size={14} className="shrink-0 text-money" />}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setHidden((s) => {
                        const n = new Set(s);
                        if (n.has(c.id)) n.delete(c.id);
                        else n.add(c.id);
                        return n;
                      })
                    }
                    disabled={cur}
                    aria-label={hid ? "Показать в переключателе" : "Скрыть из переключателя"}
                    title="Скрыть из быстрого переключателя (право остаётся)"
                    className="shrink-0 rounded-md p-1.5 text-faint hover:bg-sunken disabled:opacity-30"
                  >
                    {hid ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              );
            })}
            <div className="px-2.5 py-1.5 text-[11px] leading-snug text-faint">
              Итоги — в базовой валюте ЮЛ (курс НБ РБ, demo). Раздельный учёт сделок по ЮЛ —
              за бэкендом (пока фронт-демо).
            </div>
          </div>
        </>
      )}
    </div>
  );
}
