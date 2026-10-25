"use client";

import { useEffect, useState } from "react";
import { InstanceOrganizationGate } from "@/components/instance-organization-gate";
import { Button } from "@/components/ui/button";

const SOURCES = [
  { label: "Сделки", endpoint: "/sales/deals" },
  { label: "Закупки", endpoint: null },
  { label: "Произв. наряды", endpoint: "/production/orders" },
  { label: "Складские операции", endpoint: "/wms/ops" },
  { label: "Отгрузки", endpoint: "/logistics/shipments" },
  { label: "Платежи", endpoint: "/finance/payments" },
  { label: "Кампании", endpoint: "/marketing/campaigns" },
  { label: "Обращения", endpoint: "/service/tickets" },
  { label: "Кандидаты", endpoint: "/hr/candidates" },
  { label: "Документы офиса", endpoint: "/office/docs" },
  { label: "Юр. дела", endpoint: "/legal/cases" },
  { label: "Курсы обучения", endpoint: "/knowledge/courses" },
];

type CountResult = { kind: "loading" } | { kind: "ready"; count: number; more: boolean }
  | { kind: "error"; message: string };

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

function decodeCount(value: unknown, organizationId?: number) {
  if (organizationId === undefined) {
    return Array.isArray(value) ? { count: value.length, more: false } : null;
  }
  if (!object(value) || value.organization_id !== organizationId
    || !Array.isArray(value.items) || value.items.length > 50) return null;
  let previous = 0;
  for (const item of value.items) {
    if (!object(item) || typeof item.id !== "number"
      || !Number.isSafeInteger(item.id) || item.id <= previous) return null;
    previous = item.id;
  }
  if (value.next_after_id !== null
    && (value.items.length !== 50 || value.next_after_id !== previous)) return null;
  return { count: value.items.length, more: value.next_after_id !== null };
}

function LoadedCount({ label, endpoint, organizationId }: {
  label: string; endpoint: string; organizationId?: number;
}) {
  const [result, setResult] = useState<CountResult>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api${endpoint}`, {
          cache: "no-store", signal: controller.signal,
        });
        if (!active) return;
        if (!response.ok) {
          setResult({ kind: "error", message: response.status === 403
            ? "Нет доступа к данным." : "Не удалось загрузить данные." });
          return;
        }
        const value: unknown = await response.json();
        if (!active) return;
        const count = decodeCount(value, organizationId);
        setResult(count ? { kind: "ready", ...count }
          : { kind: "error", message: "Источник вернул некорректные данные." });
      } catch {
        if (active) setResult({ kind: "error", message: "Не удалось загрузить данные." });
      }
    })();
    return () => { active = false; controller.abort(); };
  }, [endpoint, organizationId, attempt]);

  if (result.kind === "loading") return <p role="status" className="mt-2 text-muted">Загрузка данных…</p>;
  if (result.kind === "error") return <div className="mt-2 space-y-2">
    <p role="alert" className="text-muted">{result.message}</p>
    <Button variant="secondary" aria-label={`Повторить загрузку: ${label}`} onClick={() => {
      setResult({ kind: "loading" }); setAttempt(value => value + 1);
    }}>Повторить</Button>
  </div>;
  return <div className="mt-2">
    <p className="text-sm text-muted">{organizationId === undefined ? "Загружено записей" : "Загружено заявок"}</p>
    <output className="block text-2xl font-bold text-ink">{result.count}</output>
    {result.more && <p className="text-sm text-muted">Есть ещё заявки</p>}
  </div>;
}

export function AnalyticsView() {
  return (
    <main className="flex-1 overflow-auto p-6">
      <h1 className="text-xl font-bold text-ink">Аналитика</h1>
      <p className="mt-1 text-sm text-muted">
        Показаны загруженные записи. Это не общий итог по всем данным.
      </p>
      <div className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        {SOURCES.map((s) => (
          <section key={s.label} aria-label={s.label} className="min-w-0 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="text-sm text-muted">{s.label}</h2>
            {s.endpoint === null ? <InstanceOrganizationGate>{organization => (
              <LoadedCount key={organization.id} label={s.label} organizationId={organization.id}
                endpoint={`/procurement/organizations/${organization.id}/owned-sources?kind=request`} />
            )}</InstanceOrganizationGate> : <LoadedCount key={s.endpoint} label={s.label} endpoint={s.endpoint} />}
          </section>
        ))}
      </div>
    </main>
  );
}
