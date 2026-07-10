"use client";

import { useState } from "react";

import { FunnelBoard } from "@/components/funnel/funnel-board";
import { FUNNEL_EXTRAS } from "@/lib/funnel-configs";

const STATUS_OPTIONS = [
  { value: "", label: "Все статусы" },
  { value: "new", label: "Новые" },
  { value: "in_progress", label: "В работе" },
  { value: "done", label: "Закрытые" },
];

export function ServiceRequestsClient() {
  const [statusFilter, setStatusFilter] = useState("");

  return (
    <>
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-xl font-semibold">Заявки на обслуживание</h1>
        <select
          className="ml-auto rounded border px-3 py-1.5 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <FunnelBoard
        title="Сервис и поддержка"
        subtitle="Заявки на обслуживание: ручные и автоматические (от выигранных сделок)."
        boardPath="/service/requests"
        createPath="/service/requests"
        patchPath="/service/requests"
        fields={[
          { key: "title", label: "Заголовок" },
          { key: "description", label: "Описание" },
          { key: "priority", label: "Приоритет" },
        ]}
        {...FUNNEL_EXTRAS.service}
      />
    </>
  );
}
