"use client";

import { useEffect, useState } from "react";

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
      <h1 className="text-xl font-bold text-ink">IT и настройки</h1>
      <p className="mt-1 text-sm text-muted">
        Реестр подключённых модулей ядра (модульный монолит). AI-слой включается
        переменной AIOS_AI_ENABLED.
      </p>
      {!sys && <p className="mt-5 text-sm text-muted">Загрузка…</p>}
      {sys && (
        <>
          <section className="mt-5 rounded-2xl bg-white p-5 shadow-card">
            <h2 className="font-semibold text-ink">
              Подключённые модули ({sys.loaded_modules.length})
            </h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {sys.loaded_modules.map((m) => (
                <span
                  key={m}
                  className="rounded-lg bg-blue-50 px-3 py-1 text-sm font-medium text-brand-600"
                >
                  {m}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl bg-white p-5 shadow-card">
              <h2 className="font-semibold text-ink">API-роуты ({sys.routers.length})</h2>
              <ul className="mt-3 space-y-1 text-sm text-slate-600">
                {sys.routers.map((r, i) => (
                  <li key={i}>
                    <span className="text-muted">{r.module}</span> · {r.prefix || "/"}
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-2xl bg-white p-5 shadow-card">
              <h2 className="font-semibold text-ink">События шины ({sys.events.length})</h2>
              <ul className="mt-3 max-h-48 space-y-1 overflow-y-auto text-sm text-slate-600 thin-scroll">
                {sys.events.map((e, i) => (
                  <li key={i}>
                    {e.event_type} <span className="text-muted">({e.module})</span>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="mt-4 rounded-2xl bg-white p-5 shadow-card">
            <h2 className="font-semibold text-ink">Права RBAC ({sys.permissions.length})</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {sys.permissions.map((p) => (
                <span key={p} className="rounded-lg bg-slate-100 px-3 py-1 text-xs text-slate-600">
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
