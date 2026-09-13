"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

type ControlItem = { code: string; count: number; message: string };
type Snapshot = {
  organization_id: number;
  month: string;
  status: "review_only";
  period: { closed: boolean; generation: number };
  policy: { id: number | null; effective_from: string | null; status: "verified" | "unverified" | "missing"; normative_verified: boolean; technical_preview_available: boolean; confirmation_available: boolean };
  close_blocked_by_queues: boolean;
  close_blocked_by_policy: boolean;
  blockers: ControlItem[];
  review_items: ControlItem[];
  documents: { pending_inbox: number; pending_source_controls: number };
  vat: { input_lines: number; input_registered: number; input_unregistered: number; input_unresolved: number; output_lines: number; output_registered: number; output_unregistered: number; output_unresolved: number; statutory_certified: false };
  fixed_assets: { assets_due_by_date: number; depreciation_receipts: number; assets_without_month_receipt: number; statutory_certified: false };
  production: {
    postings: number;
    material_issues: number;
    material_issue_receipts: number;
    labor_imports: number;
    labor_receipts: number;
    overhead_allocations: number;
    overhead_receipts: number;
    output_transfers: number;
    output_transfer_receipts: number;
    receipt_gap: number;
    final_cost_certified: false;
  };
  payroll: {
    gross_accruals: number;
    receipts: number;
    receipt_gap: number;
    statutory_payroll_certified: false;
    deductions_and_contributions_available: false;
  };
  repairs: { posted: number; final_cost_certified: false };
  inventory: { late_cost_postings: number; late_cost_receipts: number; final_cost_certified: false };
  foreign_trade: { entries: number; unresolved: number; statutory_certified: false };
  statutory_certified: false;
};

type Props = { org: string; month: string; disabled?: boolean };

function validItem(value: unknown): value is ControlItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.code === "string" && Number.isSafeInteger(item.count) && (item.count as number) >= 0 && typeof item.message === "string";
}

function parseSnapshot(value: unknown, org: string, month: string): Snapshot {
  if (!value || typeof value !== "object") throw new Error("Контроль закрытия вернул повреждённый ответ.");
  const data = value as Record<string, unknown>;
  const documents = data.documents as Record<string, unknown> | undefined;
  const vat = data.vat as Record<string, unknown> | undefined;
  const assets = data.fixed_assets as Record<string, unknown> | undefined;
  const production = data.production as Record<string, unknown> | undefined;
  const payroll = data.payroll as Record<string, unknown> | undefined;
  const repairs = data.repairs as Record<string, unknown> | undefined;
  const inventory = data.inventory as Record<string, unknown> | undefined;
  const foreignTrade = data.foreign_trade as Record<string, unknown> | undefined;
  const period = data.period as Record<string, unknown> | undefined;
  const policy = data.policy as Record<string, unknown> | undefined;
  if (String(data.organization_id) !== org || data.month !== month || data.status !== "review_only" || data.statutory_certified !== false
    || !period || typeof period.closed !== "boolean" || !Number.isSafeInteger(period.generation)
    || !policy || !(policy.id === null || Number.isSafeInteger(policy.id))
    || !(policy.effective_from === null || typeof policy.effective_from === "string")
    || !["verified", "unverified", "missing"].includes(policy.status as string)
    || typeof policy.normative_verified !== "boolean" || typeof policy.technical_preview_available !== "boolean"
    || typeof policy.confirmation_available !== "boolean"
    || typeof data.close_blocked_by_policy !== "boolean"
    || typeof data.close_blocked_by_queues !== "boolean"
    || !Array.isArray(data.blockers) || !data.blockers.every(validItem)
    || !Array.isArray(data.review_items) || !data.review_items.every(validItem)
    || !documents || !Number.isSafeInteger(documents.pending_inbox) || !Number.isSafeInteger(documents.pending_source_controls)
    || !vat || !["input_lines", "input_registered", "input_unregistered", "input_unresolved", "output_lines", "output_registered", "output_unregistered", "output_unresolved"].every(key => Number.isSafeInteger(vat[key]))
    || !assets || !["assets_due_by_date", "depreciation_receipts", "assets_without_month_receipt"].every(key => Number.isSafeInteger(assets[key]))
    || !production || !Number.isSafeInteger(production.postings) || production.final_cost_certified !== false
    || !payroll || !Number.isSafeInteger(payroll.gross_accruals) || !Number.isSafeInteger(payroll.receipts)
    || !Number.isSafeInteger(payroll.receipt_gap) || payroll.statutory_payroll_certified !== false
    || payroll.deductions_and_contributions_available !== false
    || !repairs || !Number.isSafeInteger(repairs.posted) || repairs.final_cost_certified !== false
    || !inventory || !Number.isSafeInteger(inventory.late_cost_postings) || inventory.final_cost_certified !== false
    || !foreignTrade || !Number.isSafeInteger(foreignTrade.entries) || !Number.isSafeInteger(foreignTrade.unresolved) || foreignTrade.statutory_certified !== false) {
    throw new Error("Контроль закрытия не соответствует выбранной организации или месяцу.");
  }
  return value as Snapshot;
}

export function AccountingClosingControls({ org, month, disabled = false }: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    if (busy || disabled || !/^\d{4}-\d{2}$/.test(month)) return;
    setBusy(true); setError(""); setSnapshot(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/periods/${month}/closing-controls`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось получить контроль закрытия.");
      setSnapshot(parseSnapshot(data, org, month));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось получить контроль закрытия."); }
    finally { setBusy(false); }
  }
  return <section aria-label="Контроль закрытия месяца" className="space-y-3 rounded-lg border border-line p-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Контроль регистров закрытия</h2><Button variant="secondary" disabled={disabled || busy || !org} onClick={() => void load()}>{busy ? "Проверка…" : "Проверить регистры"}</Button></div>
    <p className="text-sm text-muted">Read-only снимок очередей, НДС, амортизации, запасов, производства, зарплаты и ремонтов. Он не является нормативным разрешением на закрытие.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {snapshot && <div className="space-y-3 text-sm">
      <p role="status">Месяц {snapshot.month} · поколение {snapshot.period.generation} · {snapshot.period.closed ? "закрыт" : "открыт"}.</p>
      <div className="rounded border border-line p-2"><h3 className="font-medium">Учётная политика</h3>{snapshot.policy.status === "missing" ? <p className="text-red-700">На дату месяца нет применимой версии политики. Проведение и закрытие требуют явной настройки.</p> : <p>Версия № {snapshot.policy.id} действует с {snapshot.policy.effective_from}. {snapshot.policy.status === "verified" ? "Нормативная база подтверждена." : "Нормативная база не подтверждена; нормативное закрытие недоступно."} Технический preview: {snapshot.policy.technical_preview_available ? "доступен" : "недоступен"}.</p>}{snapshot.close_blocked_by_policy && <p className="mt-1 text-red-700">Закрытие заблокировано до подтверждения политики.</p>}</div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><p>Очередь документов: <strong>{snapshot.documents.pending_inbox}</strong></p><p>Первичные источники: <strong>{snapshot.documents.pending_source_controls}</strong></p><p>Входной НДС без регистра: <strong>{snapshot.vat.input_unregistered}</strong></p><p>Входной НДС с незавершённым основанием: <strong>{snapshot.vat.input_unresolved}</strong></p><p>Исходящий НДС без регистра: <strong>{snapshot.vat.output_unregistered}</strong></p><p>Исходящий НДС с незавершённым основанием: <strong>{snapshot.vat.output_unresolved}</strong></p><p>ОС без квитанции месяца: <strong>{snapshot.fixed_assets.assets_without_month_receipt}</strong></p><p>Поздние расходы запасов: <strong>{snapshot.inventory.late_cost_postings}</strong> (квитанций: {snapshot.inventory.late_cost_receipts})</p><p>ВЭД-документы: <strong>{snapshot.foreign_trade.entries}</strong></p><p>ВЭД требуют проверки: <strong>{snapshot.foreign_trade.unresolved}</strong></p><p>Проводки производства: <strong>{snapshot.production.postings}</strong></p><p>Материалы: <strong>{snapshot.production.material_issues}</strong> / квитанций {snapshot.production.material_issue_receipts}</p><p>Импорт труда: <strong>{snapshot.production.labor_imports}</strong> / квитанций {snapshot.production.labor_receipts}</p><p>Накладные: <strong>{snapshot.production.overhead_allocations}</strong> / квитанций {snapshot.production.overhead_receipts}</p><p>Выпуск: <strong>{snapshot.production.output_transfers}</strong> / квитанций {snapshot.production.output_transfer_receipts}</p><p>Производственные разрывы квитанций: <strong>{snapshot.production.receipt_gap}</strong></p><p>Валовые начисления зарплаты: <strong>{snapshot.payroll.gross_accruals}</strong> / квитанций {snapshot.payroll.receipts}</p><p>Разрывы квитанций зарплаты: <strong>{snapshot.payroll.receipt_gap}</strong></p><p>Проведённые ремонты: <strong>{snapshot.repairs.posted}</strong></p></div>
      {!!snapshot.blockers.length && <div className="rounded border border-red-300 p-2"><h3 className="font-medium">Блокирующие очереди</h3><ul className="list-disc pl-5">{snapshot.blockers.map(item => <li key={item.code}>{item.message} ({item.count})</li>)}</ul></div>}
      {!!snapshot.review_items.length && <div className="rounded border border-amber-300 p-2"><h3 className="font-medium">Требует проверки бухгалтером</h3><ul className="list-disc pl-5">{snapshot.review_items.map(item => <li key={item.code}>{item.message} ({item.count})</li>)}</ul></div>}
      {!snapshot.blockers.length && !snapshot.review_items.length && <p>Очереди и доступные локальные регистры не показывают незакрытых элементов. Нормативная сертификация остаётся отдельным шагом.</p>}
    </div>}
  </section>;
}
