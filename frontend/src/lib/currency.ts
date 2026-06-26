/**
 * Мульти-ЮЛ + валюта (порт переключателя из sales-board-mockup.html).
 * Раздельный учёт: у каждого юр-лица своя базовая валюта; суммы доски (в BYN)
 * показываются в базовой валюте текущего ЮЛ по курсу НБ РБ (demo).
 *
 * ⚠️ Фронт-демо: реальное разделение сделок по company_id + доступ пользователя +
 * живые курсы — за бэкендом (CRM.git + миграция). Здесь только вид + валюта.
 */
export interface Company {
  id: string;
  name: string;
  country: string;
  flag: string;
  base: string; // ISO-код базовой валюты ЮЛ
}

export const COMPANIES: Company[] = [
  { id: "by", name: "ООО «АкуМир»", country: "Беларусь", flag: "🇧🇾", base: "BYN" },
  { id: "ru", name: "ООО «АкуМир-РУС»", country: "Россия", flag: "🇷🇺", base: "RUB" },
  { id: "pl", name: "AkuMir Sp. z o.o.", country: "Польша", flag: "🇵🇱", base: "EUR" },
];

/** Курс к BYN (demo НБ РБ): 1 ед. валюты = FX[cur] BYN. */
export const FX: Record<string, number> = { BYN: 1, USD: 3.25, EUR: 3.55, RUB: 0.037, PLN: 0.82 };

export const CUR_SIGN: Record<string, string> = {
  BYN: "Br",
  USD: "$",
  EUR: "€",
  RUB: "₽",
  PLN: "zł",
};

/** Сумма в BYN → в базовую валюту ЮЛ (base_amount = byn / FX[base]) с подписью. */
export function formatInBase(amountByn: number, base: string): string {
  const value = amountByn / (FX[base] ?? 1);
  return new Intl.NumberFormat("ru-RU").format(Math.round(value)) + " " + (CUR_SIGN[base] ?? base);
}
