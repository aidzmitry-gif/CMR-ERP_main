export function formatMoney(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value);
}
