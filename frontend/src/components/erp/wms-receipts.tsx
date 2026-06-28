"use client";

import clsx from "clsx";
import { PackageCheck } from "lucide-react";
import Link from "next/link";

import { type Receipt, receiptStatusLabel } from "@/lib/wms-warehouse";

const STATUS_STYLES: Record<string, string> = {
  pending_qc: "bg-amber-50 text-amber-600",
  accepted: "bg-green-50 text-green-600",
  rejected: "bg-red-50 text-red-600",
  putaway_done: "bg-sunken text-muted",
};
const SOURCE_LABELS: Record<string, string> = {
  procurement: "Закупка",
  production: "Производство",
  manual: "Вручную",
};

export function WmsReceipts({ initial }: { initial: Receipt[] }) {
  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Документы приёмки. Приход на остаток пишется только после QC-приёмки (брак не идёт
        на свободный остаток). Источник прихода — закупка/производство/вручную.
      </p>
      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Документ</th>
              <th className="px-4 py-2 font-medium">Источник</th>
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 font-medium">Основание</th>
              <th className="px-4 py-2 font-medium">Статус</th>
            </tr>
          </thead>
          <tbody>
            {initial.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">
                  <PackageCheck size={20} className="mx-auto mb-1 text-faint" />
                  Приёмок пока нет
                </td>
              </tr>
            )}
            {initial.map((r) => (
              <tr key={r.id} className="border-b border-line transition-colors last:border-0 hover:bg-sunken">
                <td className="px-4 py-2.5">
                  <Link href={`/erp/wms/receipts/${r.id}`} className="font-medium text-accent-ink hover:underline">
                    {r.number || `ПРМ-${r.id}`}
                  </Link>
                </td>
                <td className="px-4 py-2.5 text-muted">{SOURCE_LABELS[r.source] ?? r.source}</td>
                <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-faint">{r.entity_ref || "—"}</td>
                <td className="px-4 py-2.5">
                  <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", STATUS_STYLES[r.status])}>
                    {receiptStatusLabel(r.status)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
