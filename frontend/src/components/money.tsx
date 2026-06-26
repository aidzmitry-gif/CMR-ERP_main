"use client";

import { useCurrency } from "@/components/kanban/currency-context";

/**
 * Сумма (хранится в BYN) в валюте выбранного ЮЛ — клиентский мостик для использования
 * курса/символа из CurrencyProvider внутри серверных компонентов (напр. PayStub в
 * server-странице карточки сделки). Вне провайдера — formatMoney по умолчанию.
 */
export function Money({ byn }: { byn: number }) {
  return <>{useCurrency().fmt(byn)}</>;
}
