"use client";

import { useEffect, useState } from "react";

import { Card, GhostButton, KpiTile, Loading, Pill } from "@/components/erp/logistics-ui";
import { auditSummary, auditVariance } from "@/lib/logistics-domain";
import {
  createAuditEntry,
  fetchAudit,
  seedAudit,
  type AuditEntry,
  type AuditReport,
} from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const DEFAULT_PERIOD = "2026-06";

const STATUS_TONE: Record<string, "slate" | "blue" | "emerald" | "amber"> = {
  ok: "emerald",
  open: "amber",
  recovered: "emerald",
  disputed: "amber",
};

export function LogisticsAudit() {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // Форма приёмки счёта (POST /costs/audit)
  const [shipmentCode, setShipmentCode] = useState("");
  const [carrierCode, setCarrierCode] = useState("");
  const [invoiceAmount, setInvoiceAmount] = useState("");
  const [expectedAmount, setExpectedAmount] = useState("");
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [lastEntry, setLastEntry] = useState<AuditEntry | null>(null);

  async function load(p: string) {
    setReport(await fetchAudit(p));
    setLoading(false);
  }

  useEffect(() => {
    void fetchAudit(period).then((data) => {
      setReport(data);
      setLoading(false);
    });
  }, [period]);

  async function onSeed() {
    setBusy(true);
    await seedAudit();
    await load(period);
    setBusy(false);
  }

  async function onSubmitInvoice() {
    setFormError(null);
    if (!shipmentCode || !carrierCode || !invoiceAmount) {
      setFormError("Заполните № отгрузки, код перевозчика и сумму счёта.");
      return;
    }
    const invoice = parseFloat(invoiceAmount);
    if (!Number.isFinite(invoice) || invoice <= 0) {
      setFormError("Сумма счёта должна быть положительным числом.");
      return;
    }
    setBusy(true);
    const expectedNum = expectedAmount ? parseFloat(expectedAmount) : null;
    const entry = await createAuditEntry({
      shipment_code: shipmentCode,
      carrier_code: carrierCode,
      invoice_amount: invoice,
      expected_amount: expectedNum != null && Number.isFinite(expectedNum) ? expectedNum : null,
      reason: reason || undefined,
    });
    setBusy(false);
    if (!entry) {
      setFormError("Не удалось зарегистрировать счёт. Проверьте код перевозчика и попробуйте снова.");
      return;
    }
    setLastEntry(entry);
    setShipmentCode("");
    setCarrierCode("");
    setInvoiceAmount("");
    setExpectedAmount("");
    setReason("");
    await load(period);
  }

  if (loading) return <Loading />;

  const items: AuditEntry[] = report?.items ?? [];

  // Свод от backend — основной; при отсутствии считаем из позиций (та же доменная логика).
  const summary = auditSummary(items);
  const checked = report?.checked ?? summary.checked;
  const discrepancies = report?.discrepancies ?? summary.discrepancies;
  const toRecover = report?.to_recover ?? summary.toRecover;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <KpiTile label="Проверено счетов" value={checked} />
        <KpiTile label="Расхождений" value={discrepancies} tone={discrepancies > 0 ? "amber" : "emerald"} />
        <KpiTile label="К возврату" value={formatByn(toRecover)} tone={toRecover > 0 ? "red" : "emerald"} />
      </div>

      <Card
        title="Зарегистрировать счёт перевозчика"
        hint="Если ожидаемая сумма не задана — посчитается из тарифа (по зоне и весу). На переплату (variance > 0) уйдёт событие freight.audit_refund в финансы."
      >
        {formError && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
            {formError}
          </div>
        )}
        {lastEntry && !formError && (
          <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            Счёт {lastEntry.shipment_code} зарегистрирован, отклонение{" "}
            <span className="font-semibold">
              {lastEntry.variance > 0 ? "+" : ""}
              {formatByn(lastEntry.variance)}
            </span>
            {lastEntry.variance > 0 && " — в финансы ушло событие к возврату."}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="№ отгрузки" value={shipmentCode} onChange={setShipmentCode} placeholder="напр. ЛОГ-2026-0099" />
          <Field label="Код перевозчика" value={carrierCode} onChange={setCarrierCode} placeholder="dpd / autolight / …" />
          <Field label="Сумма счёта (BYN)" value={invoiceAmount} onChange={setInvoiceAmount} placeholder="30.00" type="number" />
          <Field label="Ожидалось (опц.)" value={expectedAmount} onChange={setExpectedAmount} placeholder="из тарифа, если пусто" type="number" />
          <Field label="Причина (опц.)" value={reason} onChange={setReason} placeholder="напр. доплата за вес" />
          <div className="flex items-end">
            <button
              onClick={onSubmitInvoice}
              disabled={busy}
              className="w-full rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
            >
              Зарегистрировать
            </button>
          </div>
        </div>
      </Card>

      <Card
        title="Аудит счетов перевозчиков"
        hint="Сверка выставленного счёта с ожидаемым по тарифу; переплаты — к возврату."
        action={
          <div className="flex items-center gap-2">
            <input
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="ГГГГ-ММ"
              className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
            <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>
          </div>
        }
      >
        {items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">
            Счетов за {period} ещё нет. Заведите первый счёт формой выше — переплаты автоматически уйдут в финансы.
          </p>
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Отгрузка</th>
                <th className="px-3 py-2 font-medium">Перевозчик</th>
                <th className="px-3 py-2 text-right font-medium">Счёт</th>
                <th className="px-3 py-2 text-right font-medium">Ожидалось</th>
                <th className="px-3 py-2 text-right font-medium">Отклонение</th>
                <th className="px-3 py-2 font-medium">Причина</th>
                <th className="px-3 py-2 font-medium">Статус</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const variance = auditVariance(it.invoice_amount, it.expected_amount);
                return (
                  <tr key={it.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-3 py-2 text-muted">{it.shipment_code}</td>
                    <td className="px-3 py-2 text-muted">{it.carrier_code}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink">{formatByn(it.invoice_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted">{formatByn(it.expected_amount)}</td>
                    <td
                      className={
                        "px-3 py-2 text-right font-semibold tabular-nums " +
                        (variance > 0 ? "text-red-600" : variance < 0 ? "text-emerald-600" : "text-faint")
                      }
                    >
                      {variance > 0 ? "+" : ""}
                      {formatByn(variance)}
                    </td>
                    <td className="px-3 py-2 text-muted">{it.reason}</td>
                    <td className="px-3 py-2">
                      <Pill text={it.status} tone={STATUS_TONE[it.status] ?? "slate"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        )}
      </Card>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: "text" | "number";
}) {
  return (
    <label className="block text-xs text-muted">
      {label}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
      />
    </label>
  );
}
