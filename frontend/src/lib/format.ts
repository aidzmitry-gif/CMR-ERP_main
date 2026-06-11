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
