"use client";

import Link from "next/link";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useState } from "react";

import {
  fetchQualityDetail,
  qualityTone,
  type QualityDetail,
  type QualitySummaryRow,
} from "@/lib/reference-data";

const TONE_CLS: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-700",
  bad: "bg-red-50 text-red-600",
};

const KIND_LABEL: Record<string, string> = {
  missing: "Пропуски",
  duplicate: "Дубли",
  broken_ref: "Битые ссылки",
  orphan: "Сироты",
};

/** Цветной индикатор score (доля качества в %). */
function ScoreBadge({ score }: { score: number }) {
  const tone = qualityTone(score);
  return (
    <span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold tabular-nums ${TONE_CLS[tone]}`}>
      {Math.round(score * 100)}%
    </span>
  );
}

/** Детализация одного справочника (раскрытие строки) — 4 состояния. */
function DetailPanel({ refKey }: { refKey: string }) {
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [detail, setDetail] = useState<QualityDetail | null>(null);

  useEffect(() => {
    let live = true;
    setState("loading");
    fetchQualityDetail(refKey).then((d) => {
      if (!live) return;
      if (d) {
        setDetail(d);
        setState("ready");
      } else {
        setState("error");
      }
    });
    return () => {
      live = false;
    };
  }, [refKey]);

  if (state === "loading") {
    return <div className="px-4 py-3 text-[13px] text-muted">Загрузка детализации…</div>;
  }
  if (state === "error" || !detail) {
    return (
      <div className="px-4 py-3 text-[13px] text-red-600">
        Не удалось загрузить детализацию. Повторите позже.
      </div>
    );
  }
  if (detail.issues.length === 0) {
    return (
      <div className="px-4 py-3 text-[13px] text-emerald-700">
        Проблем не найдено — справочник чист.
      </div>
    );
  }
  return (
    <div className="space-y-2 px-4 py-3">
      {detail.issues.map((it, i) => (
        <div key={`${it.kind}-${it.field}-${i}`} className="rounded-lg bg-surface p-2.5 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-ink">{KIND_LABEL[it.kind] ?? it.kind}</span>
            <span className="font-mono text-[12px] text-muted">{it.field}</span>
            <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
              {it.count}
            </span>
            {it.kind === "duplicate" && detail.ref === "core.counterparties" && (
              <Link href="/erp/spravochniki/merge" className="text-[12px] font-medium text-accent hover:underline">
                → дедупликация
              </Link>
            )}
          </div>
          {it.sample_keys.length > 0 && (
            <p className="mt-1 font-mono text-[11px] text-faint">
              примеры: {it.sample_keys.join(", ")}
              {it.count > it.sample_keys.length ? " …" : ""}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export function SpravQuality({ summary }: { summary: QualitySummaryRow[] }) {
  const [open, setOpen] = useState<string | null>(null);

  // ПУСТО: эндпоинт недоступен или нет покрытых справочников
  if (summary.length === 0) {
    return (
      <div className="rounded-2xl bg-surface p-8 text-center shadow-card">
        <p className="text-sm font-medium text-muted">Аудит качества недоступен</p>
        <p className="mt-2 text-[12px] text-faint">
          Сводка появится, когда бэкенд отдаст метрики качества справочников. Данные не выдумываем.
        </p>
      </div>
    );
  }

  const worst = summary.filter((r) => r.score < 0.95).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-2xl bg-accent-soft/60 px-4 py-2.5 text-[12px] text-muted">
        <span className="font-semibold text-accent-ink">Качество справочников</span>
        <span>📊 score = доля «чистых» записей (1 − взвешенная доля проблемных)</span>
        <span>🔎 клик по строке — детали и примеры</span>
        {worst > 0 && <span className="font-semibold text-amber-700">⚠ требуют внимания: {worst}</span>}
      </div>

      <div className="overflow-x-auto rounded-2xl bg-surface shadow-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
              <th className="px-4 py-2 font-semibold">Справочник</th>
              <th className="px-4 py-2 text-right font-semibold">Всего</th>
              <th className="px-4 py-2 text-center font-semibold">Score</th>
              <th className="px-4 py-2 text-right font-semibold">Пропуски</th>
              <th className="px-4 py-2 text-right font-semibold">Дубли</th>
              <th className="px-4 py-2 text-right font-semibold">Битые</th>
              <th className="px-4 py-2 text-right font-semibold">Сироты</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {summary.map((r) => {
              const isOpen = open === r.ref;
              return (
                <Fragment key={r.ref}>
                  <tr
                    onClick={() => setOpen(isOpen ? null : r.ref)}
                    className="cursor-pointer hover:bg-sunken/50"
                  >
                    <td className="px-4 py-2.5">
                      <span className="flex items-center gap-1.5 font-medium text-ink">
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        {r.title}
                        <span className="font-mono text-[11px] text-faint">{r.ref}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{r.total}</td>
                    <td className="px-4 py-2.5 text-center">
                      <ScoreBadge score={r.score} />
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{r.by_kind.missing || "—"}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{r.by_kind.duplicate || "—"}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{r.by_kind.broken_ref || "—"}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{r.by_kind.orphan || "—"}</td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-sunken/30">
                      <td colSpan={7} className="p-0">
                        <DetailPanel refKey={r.ref} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
