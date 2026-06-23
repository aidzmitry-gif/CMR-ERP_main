export function formatMoney(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}

/** Сумма в белорусских рублях (BYN) — валюта дашборда РОП. */
export function formatByn(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " BYN";
}

/**
 * Русское склонение существительного по числу.
 * `plural(21, ["машина", "машины", "машин"])` → "машина"; `plural(22, …)` → "машины".
 * Корректно обрабатывает десятки и -teens (11–14 → форма «many»).
 */
export function plural(n: number, forms: [one: string, few: string, many: string]): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
  return forms[2];
}
