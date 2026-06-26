"use client";

import { Scale, Shield } from "lucide-react";

import type { SurvivorshipRule } from "@/lib/reference-data";
import {
  ruleProtectsFromSync,
  sourceMeta,
  strategyMeta,
  syncEntityLabel,
} from "@/lib/spravochniki-card";

const TONE_CLASS: Record<string, string> = {
  egr: "bg-emerald-50 text-emerald-700",
  erp: "bg-violet-50 text-violet-700",
  manual: "bg-sunken text-muted",
  onec: "bg-blue-50 text-blue-700",
  bitrix: "bg-amber-50 text-amber-700",
};

/** Цепочка источников по приоритету (egr → erp → 1c …) маленькими бейджами. */
function PriorityChain({ sources }: { sources: string[] }) {
  if (sources.length === 0) return <span className="text-faint">—</span>;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {sources.map((s, i) => {
        const m = sourceMeta(s);
        return (
          <span key={s} className="flex items-center gap-1">
            {i > 0 && <span className="text-faint">›</span>}
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONE_CLASS[m.tone]}`}
            >
              <span aria-hidden>{m.icon}</span>
              {m.label}
            </span>
          </span>
        );
      })}
    </span>
  );
}

export function SpravMergeRules({ rules }: { rules: SurvivorshipRule[] }) {
  // группируем по сущности (порядок сохраняем: backend отдаёт отсортированным)
  const byEntity = new Map<string, SurvivorshipRule[]>();
  for (const r of rules) {
    const list = byEntity.get(r.entity_type) ?? [];
    list.push(r);
    byEntity.set(r.entity_type, list);
  }
  const protectedCount = rules.filter(ruleProtectsFromSync).length;

  return (
    <div className="flex-1 overflow-y-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl space-y-4">

        {/* Header */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
                <Scale className="h-5 w-5 text-faint" />
                Правила слияния
              </h1>
              <p className="mt-1 max-w-3xl text-sm text-muted">
                Survivorship (M2): для каждого поля задано, кто «побеждает» при конфликте
                источников. Это закрывает главную причину, по которой ERP оставался «вторым после
                1С»: ручная правка переживает синк, а реквизиты ЕГР не затираются импортом. Правила
                хранятся как данные (таблица <span className="font-mono">survivorship_rule</span>).
              </p>
            </div>
            {rules.length > 0 && (
              <span className="flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[12px] text-emerald-700">
                <Shield className="h-4 w-4" />
                {protectedCount} защищены от синка
              </span>
            )}
          </div>
        </div>

        {rules.length === 0 ? (
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <p className="text-sm text-muted">
              Правил пока нет — все поля берут дефолт «непустое замещает». Добавьте правило, чтобы
              закрепить поле за источником.
            </p>
          </div>
        ) : (
          [...byEntity.entries()].map(([entity, list]) => (
            <div key={entity} className="rounded-2xl bg-surface p-5 shadow-card">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                {syncEntityLabel(entity)}
              </p>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                      <th className="px-3 py-2 font-semibold">Поле</th>
                      <th className="px-3 py-2 font-semibold">Стратегия</th>
                      <th className="px-3 py-2 font-semibold">Приоритет источников</th>
                      <th className="px-3 py-2 font-semibold">Защита от синка</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {list.map((r) => {
                      const sm = strategyMeta(r.strategy);
                      const protectedFromSync = ruleProtectsFromSync(r);
                      return (
                        <tr key={r.id} className="align-top hover:bg-sunken/60">
                          <td className="px-3 py-2.5 font-mono text-[13px] text-ink">{r.field}</td>
                          <td className="px-3 py-2.5">
                            <span className="text-ink">{sm.label}</span>
                            {sm.hint && (
                              <p className="mt-0.5 text-[11px] text-faint">{sm.hint}</p>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <PriorityChain sources={r.source_priority} />
                          </td>
                          <td className="px-3 py-2.5">
                            {protectedFromSync ? (
                              <span className="inline-flex items-center gap-1 text-emerald-700">
                                <Shield className="h-3.5 w-3.5" /> защищено
                              </span>
                            ) : (
                              <span className="text-faint">— синк обновит</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}

        <p className="px-1 text-[11px] text-faint">
          «Защита от синка» = поле закреплено правилом за источником выше 1С (или «только вручную»)
          → импорт его не перезапишет. Незащищённые поля синк обновляет. Правила применяются и при
          импорте из 1С, и при слиянии дублей.
        </p>

      </div>
    </div>
  );
}
