"use client";

import { Check, ChevronDown } from "lucide-react";
import { useState } from "react";
import { useCurrency } from "./currency-context";

/** Display currency only; the existing context stores the legacy selection IDs. */
export function CompanySwitcher() {
  const { company, companies, setCompany } = useCurrency();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Валюта отображения сумм"
        aria-label={`Валюта сумм: ${company.base}`}
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-sunken"
      >
        <span>Валюта сумм:</span>
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
              Валюта сумм
            </div>
            {companies.map((c) => {
              const cur = c.id === company.id;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => {
                    setCompany(c.id);
                    setOpen(false);
                  }}
                  className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] hover:bg-sunken ${
                    cur ? "font-semibold text-ink" : "text-muted"
                  }`}
                >
                  <span className="flex-1">{c.base}</span>
                  {cur && <Check size={14} className="shrink-0 text-money" />}
                </button>
              );
            })}
            <div className="px-2.5 py-1.5 text-[11px] leading-snug text-faint">
              Суммы пересчитаны из BYN по курсу НБ РБ.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
