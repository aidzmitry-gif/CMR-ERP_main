"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldCheck, UserPlus } from "lucide-react";

interface SystemInfo {
  loaded_modules: string[];
  routers: { module: string; prefix: string }[];
  events: { module: string; event_type: string }[];
  permissions: string[];
  widgets: { key: string; title: string }[];
}

export function SettingsView() {
  const [sys, setSys] = useState<SystemInfo | null>(null);

  useEffect(() => {
    void fetch("/api/system/modules", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setSys)
      .catch(() => {});
  }, []);

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-ink">IT и настройки</h1>
          <p className="mt-1 text-sm text-muted">
            Реестр подключённых модулей ядра (модульный монолит). AI-слой включается
            переменной AIOS_AI_ENABLED.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/erp/settings/access" className="inline-flex items-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink hover:border-accent">
            <ShieldCheck size={16} aria-hidden="true" />
            Сотрудники CRM и роли
          </Link>
          <Link href="/erp/settings/invitations" className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white shadow-sm hover:brightness-110 focus:outline-none focus:ring-2 focus:ring-accent/40">
            <UserPlus size={16} aria-hidden="true" />
            Приглашения сотрудников
          </Link>
        </div>
      </div>
      {!sys && <p className="mt-5 text-sm text-muted">Загрузка…</p>}
      {sys && (
        <>
          <section className="mt-5 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">
              Подключённые модули ({sys.loaded_modules.length})
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {sys.loaded_modules.map((m) => (
                <span
                  key={m}
                  className="rounded-lg bg-blue-50 px-3 py-1 text-sm font-medium text-accent-ink"
                >
                  {m}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <h2 className="font-semibold text-ink">API-роуты ({sys.routers.length})</h2>
              <ul className="mt-3 space-y-1 text-sm text-muted">
                {sys.routers.map((r, i) => (
                  <li key={i}>
                    <span className="text-muted">{r.module}</span> · {r.prefix || "/"}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <h2 className="font-semibold text-ink">События шины ({sys.events.length})</h2>
              <ul className="mt-3 max-h-48 space-y-1 overflow-y-auto text-sm text-muted thin-scroll">
                {sys.events.map((e, i) => (
                  <li key={i}>
                    {e.event_type} <span className="text-muted">({e.module})</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="mt-4 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">Права RBAC ({sys.permissions.length})</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {sys.permissions.map((p) => (
                <span key={p} className="rounded-lg bg-sunken px-3 py-1 text-xs text-muted">
                  {p}
                </span>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
