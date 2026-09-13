export type ExportTrial = {
  account: string; title: string; currency: string; dimensions: Record<string, string>; off_balance: boolean;
  opening: string; debit: string; credit: string; closing: string;
  original_opening?: string; original_debit?: string; original_credit?: string; original_closing?: string;
  quantity_opening?: string; quantity_debit?: string; quantity_credit?: string; quantity_closing?: string;
};
export type ExportReport = { organization_id: number; from: string; to: string; status: string; pending_documents: number; trial_balance: ExportTrial[] };
const amounts = ["opening", "debit", "credit", "closing", "original_opening", "original_debit", "original_credit", "original_closing", "quantity_opening", "quantity_debit", "quantity_credit", "quantity_closing"] as const;
const quote = (value: string, numeric = false) => {
  // Quoting alone does not prevent spreadsheet formulas. Numeric fields come
  // from exact decimal strings; untrusted text is exported as spreadsheet text.
  const safe = !numeric && /^[\s]*[=+@-]/.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
};
export function trialBalanceCsv(report: ExportReport): string {
  const headers = ["Тип строки", "Юрлицо ID", "С", "По", "Статус", "Не проведено документов", "Счёт", "Название", "Аналитика JSON", "Валюта исходных сумм", "Забалансовый", "Сальдо начальное BYN", "Дебет BYN", "Кредит BYN", "Сальдо конечное BYN", "Сальдо начальное в валюте", "Дебет в валюте", "Кредит в валюте", "Сальдо конечное в валюте", "Количество начальное", "Количество дебет", "Количество кредит", "Количество конечное"];
  const metadata = [String(report.organization_id), report.from, report.to, report.status, String(report.pending_documents)];
  const rows = [headers.map((value) => quote(value)).join(";")];
  // Keep book, dates and preliminary status even for an empty trial balance.
  rows.push(["report", ...metadata, ...Array(headers.length - 6).fill("")].map((value) => quote(value)).join(";"));
  for (const row of report.trial_balance) {
    const dimensions = JSON.stringify(Object.fromEntries(Object.entries(row.dimensions).sort(([a], [b]) => a.localeCompare(b))));
    const cells = ["balance", ...metadata, row.account, row.title, dimensions, row.currency, row.off_balance ? "Да" : "Нет"];
    const numeric = amounts.map((field) => {
      const value = row[field];
      if (value === undefined) return quote("");
      if (!/^-?\d+(?:\.\d+)?$/.test(value)) throw new Error("Некорректная сумма в отчёте. Обновите ведомость.");
      return quote(value, true);
    });
    rows.push([...cells.map((value) => quote(value)), ...numeric].join(";"));
  }
  return `\uFEFF${rows.join("\r\n")}\r\n`;
}

export function downloadTrialBalance(report: ExportReport) {
  const csv = trialBalanceCsv(report);
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `osv-${report.organization_id}-${report.from}-${report.to}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
