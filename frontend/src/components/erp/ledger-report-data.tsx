import type { ReactNode } from "react";

type Scope = { org: string | number; start: string; end: string };
type DataState = "empty" | "unknown" | "populated";
const money = (value: unknown) => typeof value === "string" && /^-?\d+\.\d{2}$/.test(value);

export function ledgerReportDataState(value: unknown, scope: Scope): DataState {
  if (!value || typeof value !== "object") return "unknown";
  const report = value as Record<string, unknown>;
  if (!Number.isSafeInteger(report.organization_id) || Number(report.organization_id) <= 0
    || String(report.organization_id) !== String(scope.org) || report.from !== scope.start || report.to !== scope.end
    || !Array.isArray(report.trial_balance)) return "unknown";
  const valid = report.trial_balance.every((row: unknown) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return false;
    const item = row as Record<string, unknown>;
    return typeof item.account === "string" && item.account.trim().length > 0
      && typeof item.title === "string" && typeof item.off_balance === "boolean"
      && typeof item.currency === "string" && item.currency.trim().length > 0
      && item.dimensions !== null && typeof item.dimensions === "object" && !Array.isArray(item.dimensions)
      && Object.values(item.dimensions).every(value => typeof value === "string")
      && [item.opening, item.debit, item.credit, item.closing].every(money);
  });
  return !valid ? "unknown" : report.trial_balance.length ? "populated" : "empty";
}

export function LedgerReportData({ report, scope, children }: {
  report: unknown; scope: Scope; children: () => ReactNode;
}) {
  const state = ledgerReportDataState(report, scope);
  if (state === "populated") return children();
  return <div role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900">
    <p className="font-semibold">{state === "empty" ? "Нет учётных данных ERP" : "Данные отчёта пока не подтверждены"}</p>
    <p className="mt-2">{state === "empty"
      ? `В бухгалтерской книге ERP нет проведённых строк на ${scope.end}. Отсутствие записей не подтверждает нулевые показатели компании. Проверьте начальные остатки и проведённые документы.`
      : "Не удалось подтвердить строки бухгалтерской книги, организацию или период ответа. Финансовые итоги и выгрузка недоступны до получения корректного отчёта."}</p>
  </div>;
}
