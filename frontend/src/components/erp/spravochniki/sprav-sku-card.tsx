"use client";

import { Package, Wallet } from "lucide-react";

import { formatByn } from "@/lib/format";
import type { SkuCard } from "@/lib/reference-data";
import { provenanceCounts } from "@/lib/spravochniki-card";

import { Field } from "./provenance-badge";

/** Значение JSON-атрибута → строка для таблицы (объект/массив — компактный JSON). */
function attrValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function SpravSkuCard({ card }: { card: SkuCard }) {
  const prov = card.provenance ?? {};
  const counts = provenanceCounts(prov);
  const attrs = Object.entries(card.attributes ?? {});

  return (
    <div className="flex-1 overflow-y-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl space-y-4">

        {/* Header */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-start gap-3">
            <Package className="mt-0.5 h-5 w-5 text-faint" />
            <h1 className="text-xl font-bold text-ink">{card.title}</h1>
            <span className="mt-0.5 rounded-full bg-sunken px-2 py-0.5 font-mono text-[11px] text-muted">
              {card.code}
            </span>
            {card.is_active ? (
              <span className="mt-0.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
                Активна
              </span>
            ) : (
              <span className="mt-0.5 rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                В архиве
              </span>
            )}
          </div>
        </div>

        {/* Two-column grid */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">

          {/* Left — горячие поля + переменные характеристики */}
          <div className="space-y-4">

            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Карточка товара
                </p>
                {counts.length > 0 && (
                  <p className="text-[11px] text-faint">справа от поля — источник значения</p>
                )}
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Field className="sm:col-span-2" label="Наименование" value={card.title} prov={prov.title} />
                <Field label="Код / артикул" value={card.code} prov={prov.code} mono />
                <Field label="Ед. изм." value={card.unit ?? "—"} prov={prov.unit} />
                <Field
                  label="Вес, кг"
                  value={card.weight_kg != null ? String(card.weight_kg) : "—"}
                  prov={prov.weight_kg}
                  mono
                />
                <Field
                  label="Код ТН ВЭД"
                  value={card.tnved_code ?? "—"}
                  prov={prov.tnved_code}
                  mono
                />
                <Field
                  label="Срок годности, дн."
                  value={card.shelf_life_days != null ? String(card.shelf_life_days) : "—"}
                  prov={prov.shelf_life_days}
                  mono
                />
              </div>
            </div>

            {/* Переменные характеристики (JSONB-хвост) */}
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Переменные характеристики
                </p>
                <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-faint">
                  хранится: JSONB <span className="font-mono">attributes</span>
                </span>
              </div>
              {attrs.length === 0 ? (
                <p className="mt-3 text-sm text-muted">Характеристик не задано</p>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    <tbody className="divide-y divide-line">
                      {attrs.map(([k, v]) => (
                        <tr key={k} className="hover:bg-sunken/60">
                          <td className="py-2 pr-3 align-top text-muted">{k}</td>
                          <td className="py-2 text-ink">{attrValue(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-3 text-[11px] text-faint">
                «Горячие» поля (вес, ТН ВЭД, срок) вынесены в типизированные колонки — по ним
                фильтр/расчёты; остальное — гибкий JSON-хвост.
              </p>
            </div>
          </div>

          {/* Right — себестоимость + происхождение */}
          <div className="space-y-4">

            {/* Себестоимость (landed cost) — приоритет №1 (деньги/маржа на видном месте) */}
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Себестоимость партии
              </p>
              {card.landed_cost != null ? (
                <>
                  <p className="mt-2 flex items-center gap-1.5 text-2xl font-bold text-money">
                    <Wallet className="h-5 w-5" />
                    {formatByn(card.landed_cost)}
                  </p>
                  <p className="mt-2 text-[12px] text-muted">
                    Landed cost последней партии — из модуля закупок (выкуп → машина). Видна продавцу
                    в момент сделки для контроля маржи.
                  </p>
                </>
              ) : (
                <>
                  <p className="mt-2 text-sm font-medium text-muted">Нет расчёта</p>
                  <p className="mt-2 text-[12px] text-faint">
                    Себестоимость появится после расчёта партии в закупках. Отсутствие не маскируем
                    нулём — пока расчёта нет, поле пустое.
                  </p>
                </>
              )}
            </div>

            {counts.length > 0 && (
              <div className="rounded-2xl bg-surface p-5 shadow-card">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Происхождение полей
                </p>
                <div className="mt-3 space-y-1.5 text-[12px]">
                  {counts.map(({ source, meta, count }) => (
                    <div key={source} className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5 text-muted">
                        <span aria-hidden>{meta.icon}</span>
                        {meta.label}
                      </span>
                      <span className="font-semibold text-ink">{count}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-3 border-t border-line pt-3 text-[11px] text-faint">
                  Источник известен по каждому полю — синк из 1С не затирает закреплённые правилами.
                </p>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
