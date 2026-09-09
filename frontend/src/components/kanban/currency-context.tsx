"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { COMPANIES, formatInBase, type Company } from "@/lib/currency";
import { formatMoney } from "@/lib/format";

interface CurrencyCtx {
  company: Company;
  companies: Company[];
  setCompany: (id: string) => void;
  /** Форматировать сумму (хранится в BYN) в базовой валюте текущего ЮЛ. */
  fmt: (amountByn: number) => string;
}

const DEFAULT_COMPANY = COMPANIES[0]; // by · BYN

// Дефолт вне провайдера (design-страницы, тесты, ERP-экраны) — прежнее поведение
// (₽ через formatMoney), чтобы порт не менял их и не падал без провайдера.
const CurrencyContext = createContext<CurrencyCtx>({
  company: DEFAULT_COMPANY,
  companies: COMPANIES,
  setCompany: () => {},
  fmt: formatMoney,
});

export const useCurrency = () => useContext(CurrencyContext);

const STORE_KEY = "salesCompany"; // общий ключ со всеми экранами CRM (как в макете)

export function CurrencyProvider({ children }: { children: React.ReactNode }) {
  const [id, setId] = useState(DEFAULT_COMPANY.id);

  // localStorage читаем после маунта: SSR и первый клиент-рендер = 'by' (нет
  // рассинхрона гидрации), затем применяем сохранённый выбор.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      if (saved && COMPANIES.some((c) => c.id === saved)) setId(saved);
    } catch {
      /* localStorage недоступен — остаёмся на дефолте */
    }
  }, []);

  const setCompany = useCallback((next: string) => {
    setId(next);
    try {
      localStorage.setItem(STORE_KEY, next);
    } catch {
      /* no-op */
    }
  }, []);

  const company = COMPANIES.find((c) => c.id === id) ?? DEFAULT_COMPANY;
  const [quote, setQuote] = useState<{ currency: string; date: string; rate: number } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      if (company.base === "BYN") return;
      const on = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Minsk" }).format(new Date());
      try {
        const response = await fetch(`/api/system/fx/${company.base}?on=${on}`, { signal: controller.signal });
        if (!response.ok) throw new Error("rate unavailable");
        const value = await response.json();
        if (value.currency !== company.base || value.date !== on) throw new Error("wrong quote");
        if (!controller.signal.aborted) setQuote({ currency: value.currency, date: on, rate: Number(value.rate) });
      } catch {
        if (!controller.signal.aborted) setQuote(null);
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 60_000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [company.base]);
  const fmt = useCallback((amountByn: number) => {
    const on = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Minsk" }).format(new Date());
    const rate = company.base === "BYN" ? 1 : quote?.currency === company.base && quote.date === on ? quote.rate : NaN;
    return formatInBase(amountByn, company.base, rate);
  }, [company.base, quote]);

  return (
    <CurrencyContext.Provider value={{ company, companies: COMPANIES, setCompany, fmt }}>
      {children}
    </CurrencyContext.Provider>
  );
}
