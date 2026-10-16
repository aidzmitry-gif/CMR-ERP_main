const labels: Record<string, string> = {
  policy_id: "Учётная политика", document_date: "Дата первичного документа",
  posting_date: "Дата отражения", explanation: "Содержание операции",
  recognition_basis: "Основание признания выручки", unit_basis: "Соответствие единиц",
  cost_allocation: "Распределение стоимости", vat_rounding: "Округление НДС",
  allocations: "Распределение", commercial_lines: "Условия продажи",
  account: "Счёт запасов", lot: "Партия", quantity: "Количество",
  expense_account: "Счёт себестоимости", expense_dimensions: "Аналитика расходов",
  net_amount: "Сумма без НДС", vat_rate: "Ставка НДС", vat_basis: "Основание НДС",
  buyer_account: "Счёт покупателя", revenue_account: "Счёт выручки",
  vat_revenue_account: "НДС из выручки", vat_payable_account: "НДС к уплате",
  buyer_dimensions: "Аналитика покупателя", revenue_dimensions: "Аналитика выручки",
  vat_dimensions: "Аналитика НДС", counterparty: "Контрагент", contract: "Договор",
  settlement_document: "Документ расчётов", department: "Подразделение",
};

export function shipmentValidationMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  const fallback = "Проверьте распределения, суммы, счета и обязательную аналитику.";
  if (!Array.isArray(detail)) return fallback;
  const fields = detail.flatMap((item: unknown) => {
    if (!item || typeof item !== "object" || !("loc" in item) || !Array.isArray(item.loc)) return [];
    const path = item.loc.filter((part: unknown) => part !== "body").map((part: unknown) =>
      typeof part === "number" && Number.isSafeInteger(part) && part >= 0 ? `№ ${part + 1}` :
        typeof part === "string" ? labels[part] ?? "Поле" : "Поле");
    return path.length ? [path.join(" → ")] : [];
  });
  const unique = [...new Set(fields)];
  return unique.length ? `Проверьте поля: ${unique.slice(0, 8).join("; ")}${unique.length > 8 ? "; и другие поля" : ""}.` : fallback;
}
