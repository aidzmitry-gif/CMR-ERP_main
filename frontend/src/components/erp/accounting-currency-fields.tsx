"use client";

import { Input } from "@/components/ui/input";

export type CurrencyFields = {
  currency?: string; original_amount?: string; rate?: string; rate_scale?: number;
  rate_date?: string; rate_source?: string; quantity?: string;
};

export function AccountingCurrencyFields({ value, currency, quantity, onChange }: {
  value: CurrencyFields; currency: boolean; quantity: boolean;
  onChange: (patch: CurrencyFields) => void;
}) {
  return <div className="grid gap-3 md:grid-cols-3">
    {quantity && <label className="text-sm">Количество<Input inputMode="decimal" value={value.quantity || ""} onChange={(e) => onChange({ quantity: e.target.value || undefined })} /></label>}
    {currency && <label className="text-sm">Валюта<Input maxLength={3} value={value.currency || "BYN"} onChange={(e) => { const code = e.target.value.toUpperCase(); onChange(code === "BYN" ? { currency: code, original_amount: undefined, rate: undefined, rate_scale: undefined, rate_date: undefined, rate_source: undefined } : { currency: code }); }} /></label>}
    {currency && value.currency && value.currency !== "BYN" && <>
      <label className="text-sm">Сумма в валюте<Input inputMode="decimal" value={value.original_amount || ""} onChange={(e) => onChange({ original_amount: e.target.value })} /></label>
      <label className="text-sm">Курс в BYN<Input inputMode="decimal" value={value.rate || ""} onChange={(e) => onChange({ rate: e.target.value })} /></label>
      <label className="text-sm">За единиц валюты<Input type="number" min="1" step="1" value={value.rate_scale ?? ""} onChange={(e) => onChange({ rate_scale: e.target.value === "" ? undefined : Number(e.target.value) })} /></label>
      <label className="text-sm">Дата курса<Input type="date" value={value.rate_date || ""} onChange={(e) => onChange({ rate_date: e.target.value })} /></label>
      <label className="text-sm">Источник курса<Input value={value.rate_source || ""} onChange={(e) => onChange({ rate_source: e.target.value })} placeholder="Документ или официальный источник" /></label>
      <p className="text-sm text-muted md:col-span-3">Укажите сумму строки в BYN по документированному курсу. Сервер проверит пересчёт с учётом масштаба курса.</p>
    </>}
  </div>;
}
