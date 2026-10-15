"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type HistoricalOperation = { id: number; number: string; title: string; stage: string };

export function WmsOperationHistory() {
  const [rows, setRows] = useState<HistoricalOperation[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/wms/ops", { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Не удалось загрузить историю операций.");
        const data: unknown = await response.json();
        if (!Array.isArray(data) || data.some(row => !row || !Number.isSafeInteger(row.id)
          || row.id <= 0 || typeof row.number !== "string" || typeof row.title !== "string"
          || typeof row.stage !== "string")) throw new Error("Ответ истории операций требует проверки.");
        if (!controller.signal.aborted) setRows(data);
      })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "История недоступна."); });
    return () => controller.abort();
  }, []);
  return <main className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">История складских операций</h1>
      <p>Прежние операции доступны только для просмотра: в них не указан отдельный склад организации.
        Новые операции выполняются через документы и задачи выбранного склада.</p>
      <Link className="text-accent underline" href="/erp/wms">Перейти к складу</Link>
      {error && <p role="alert">{error}</p>}
      {!error && rows === null && <p role="status">Загрузка истории…</p>}
      {rows?.length === 0 && <p>Исторических операций нет.</p>}
      {!!rows?.length && <table className="w-full text-left text-sm">
        <thead><tr><th>Номер</th><th>Описание</th><th>Стадия</th></tr></thead>
        <tbody>{rows.map(row => <tr className="border-t border-line" key={row.id}>
          <td className="py-3">{row.number}</td><td>{row.title}</td><td>{row.stage}</td>
        </tr>)}</tbody>
      </table>}
    </main>;
}
