"use client";

import { Mail, Phone, Star, User } from "lucide-react";

import type { CounterpartyCard } from "@/lib/reference-data";
import { formatAuditDate, groupAliasesBySource } from "@/lib/spravochniki-card";

export function SpravCard({ card }: { card: CounterpartyCard }) {
  const aliasesBySource = groupAliasesBySource(card.aliases);
  const sourceCount = card.aliases.length;

  return (
    <div className="flex-1 overflow-y-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl space-y-4">

        {/* Header */}
        <div className="rounded-2xl bg-white p-5 shadow-card">
          <div className="flex flex-wrap items-start gap-3">
            <h1 className="text-xl font-bold text-ink">{card.name}</h1>
            <Star className="mt-1 h-4 w-4 fill-brand text-brand" />
            {card.unp && (
              <span className="mt-0.5 font-mono text-[13px] text-muted">УНП {card.unp}</span>
            )}
            {card.is_active ? (
              <span className="mt-0.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                Активен
              </span>
            ) : (
              <span className="mt-0.5 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
                В архиве
              </span>
            )}
            <span className="mt-0.5 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-500">
              #{card.id}
            </span>
          </div>
        </div>

        {/* Two-column grid */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">

          {/* Left — Реквизиты + Контакты */}
          <div className="space-y-4">

            <div className="rounded-2xl bg-white p-5 shadow-card">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Реквизиты
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <p className="text-[12px] text-slate-500">Наименование</p>
                  <div className="mt-1 rounded-xl bg-slate-50 px-3 py-2 text-sm text-ink">
                    {card.name}
                  </div>
                </div>
                <div>
                  <p className="text-[12px] text-slate-500">УНП</p>
                  <div className="mt-1 rounded-xl bg-slate-50 px-3 py-2 font-mono text-sm text-ink">
                    {card.unp ?? "—"}
                  </div>
                </div>
                <div>
                  <p className="text-[12px] text-slate-500">Статус</p>
                  <div className="mt-1 rounded-xl bg-slate-50 px-3 py-2 text-sm">
                    {card.is_active ? (
                      <span className="text-emerald-700">Активен</span>
                    ) : (
                      <span className="text-slate-500">В архиве</span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-2xl bg-white p-5 shadow-card">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Контакты
              </p>
              {card.contacts.length === 0 ? (
                <p className="mt-3 text-sm text-muted">Контактов не найдено</p>
              ) : (
                <div className="mt-3 space-y-2">
                  {card.contacts.map((c) => (
                    <div key={c.id} className="flex items-start gap-3 rounded-xl bg-slate-50 px-3 py-2">
                      <User className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-ink">{c.full_name}</span>
                          {c.is_primary && (
                            <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[11px] text-brand-600">
                              основной
                            </span>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[12px] text-muted">
                          {c.phone && (
                            <span className="flex items-center gap-1">
                              <Phone className="h-3 w-3" />
                              {c.phone}
                            </span>
                          )}
                          {c.email && (
                            <span className="flex items-center gap-1">
                              <Mail className="h-3 w-3" />
                              {c.email}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right — Golden record + Слитые дубли */}
          <div className="space-y-4">

            <div className="rounded-2xl bg-white p-5 shadow-card">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Golden record
              </p>
              <p className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-ink">
                <Star className="h-4 w-4 fill-brand text-brand" />
                {sourceCount > 0
                  ? `Собрана из ${sourceCount} источник${sourceCount === 1 ? "а" : "ов"}`
                  : "Эталон без алиасов"}
              </p>
              {Object.keys(aliasesBySource).length > 0 && (
                <div className="mt-3 space-y-2">
                  {Object.entries(aliasesBySource).map(([source, list]) =>
                    list.map((a) => (
                      <div
                        key={`${source}-${a.external_ref}`}
                        className="flex items-center justify-between gap-2"
                      >
                        <span className="truncate rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-mono text-slate-600">
                          {source} · {a.external_ref}
                        </span>
                        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
                          alias
                        </span>
                      </div>
                    )),
                  )}
                </div>
              )}
              <p className="mt-3 text-[11px] text-slate-400">
                Документы ссылаются только на эталон; дубли хранятся как алиасы.
              </p>
            </div>

            {card.merged_duplicates.length > 0 && (
              <div className="rounded-2xl bg-white p-5 shadow-card">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Слитые дубли
                </p>
                <div className="mt-3 space-y-2">
                  {card.merged_duplicates.map((d) => (
                    <div key={d.id} className="flex items-center gap-2">
                      <span className="text-[11px] text-slate-400">🗃</span>
                      <span className="min-w-0 flex-1 truncate text-sm text-slate-600">{d.name}</span>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-500">
                        #{d.id}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-slate-400">Слияние обратимо.</p>
              </div>
            )}
          </div>
        </div>

        {/* Audit */}
        <div className="rounded-2xl bg-white p-5 shadow-card">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            История изменений (аудит)
          </p>
          {card.audit.length === 0 ? (
            <p className="mt-3 text-sm text-muted">Истории изменений пока нет</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-y border-slate-100 bg-slate-50/60 text-left text-[11px] uppercase tracking-wide text-slate-400">
                    <th className="px-3 py-2 font-semibold">Действие</th>
                    <th className="px-3 py-2 font-semibold">Кто</th>
                    <th className="px-3 py-2 font-semibold">Когда</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {card.audit.map((a) => (
                    <tr key={a.id} className="hover:bg-slate-50/60">
                      <td className="px-3 py-2.5">{a.action}</td>
                      <td className="px-3 py-2.5 text-muted">{a.actor}</td>
                      <td className="px-3 py-2.5 font-mono text-[13px] text-slate-500">
                        {formatAuditDate(a.ts)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
