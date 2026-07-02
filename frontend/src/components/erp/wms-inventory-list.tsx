"use client";

import clsx from "clsx";
import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  createInventory,
  type InventoryCount,
  type InventoryStatus,
  inventoryStatusLabel,
} from "@/lib/wms-inventory";

const STATUS_STYLES: Record<InventoryStatus, string> = {
  open: "bg-amber-50 text-amber-600",
  done: "bg-green-50 text-green-600",
  canceled: "bg-sunken text-muted",
};

export function WmsInventoryList({ initial }: { initial: InventoryCount[] }) {
  const router = useRouter();
  const [warehouse, setWarehouse] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function onCreate() {
    if (!warehouse.trim()) {
      setError(true);
      setTimeout(() => setError(false), 900);
      return;
    }
    setBusy(true);
    const doc = await createInventory(warehouse.trim());
    setBusy(false);
    if (doc) router.push(`/erp/wms/inventory/${doc.id}`);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Пересчёт склада со сверкой против 1С. Ожидаемое подтягивается из 1С (зеркало), факт
        вносит кладовщик — система считает недостачи/излишки. Остатки в 1С не меняются.
      </p>

      <div className="mt-4 flex items-center gap-2">
        <input
          value={warehouse}
          onChange={(e) => setWarehouse(e.target.value)}
          placeholder="Склад для инвентаризации (напр. Минск (центр.))"
          className={clsx(
            "min-w-0 flex-1 rounded-lg border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent",
            error ? "border-amber-500" : "border-line",
          )}
        />
        <button
          onClick={onCreate}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          <Plus size={16} /> Новая инвентаризация
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Документ</th>
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 font-medium">Создан</th>
            </tr>
          </thead>
          <tbody>
            {initial.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-muted">
                  <ClipboardList size={20} className="mx-auto mb-1 text-faint" />
                  Инвентаризаций пока нет
                </td>
              </tr>
            )}
            {initial.map((d) => (
              <tr key={d.id} className="border-b border-line transition-colors last:border-0 hover:bg-sunken">
                <td className="px-4 py-2.5">
                  <Link href={`/erp/wms/inventory/${d.id}`} className="font-medium text-accent-ink hover:underline">
                    {d.number || `ИНВ-${d.id}`}
                  </Link>
                </td>
                <td className="px-4 py-2.5 text-muted">{d.warehouse}</td>
                <td className="px-4 py-2.5">
                  <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", STATUS_STYLES[d.status])}>
                    {inventoryStatusLabel(d.status)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-faint">
                  {d.created_at ? new Date(d.created_at).toLocaleDateString("ru-RU") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
