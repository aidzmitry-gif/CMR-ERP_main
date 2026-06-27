"use client";

import { useEffect, useState } from "react";

import { Card, KpiTile, Loading, Pill } from "@/components/erp/logistics-ui";
import { fetchImportBoard, type ImportBoard } from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

// Информационная панель импорта из Китая: наблюдение цепочки фрахт-форвардинга
// (фабрика → консолидация → плечо → таможня → склад) по событиям import.*.
// ВАЖНО: приёмка на склад и остатки здесь НЕ ведутся — это procurement→wms
// (двойной учёт запрещён). Стадия «склад» тут лишь отражает факт прихода.

const PRIORITY_TONE: Record<string, "slate" | "amber" | "red"> = {
  Высокий: "red",
  Средний: "amber",
  Низкий: "slate",
};

export function LogisticsImport() {
  const [board, setBoard] = useState<ImportBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchImportBoard()
      .then((b) => {
        if (!alive) return;
        setBoard(b);
        setFailed(b === null);
        setLoading(false);
      })
      .catch(() => {
        if (!alive) return;
        setFailed(true);
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <Loading />;

  // Ошибка фетча (backend недоступен) — честно отличаем от «данных нет».
  if (failed)
    return (
      <Card title="Импорт из Китая">
        <p className="py-6 text-center text-sm text-muted">
          Не удалось загрузить цепочку импорта. Проверьте подключение к сервису логистики и обновите страницу.
        </p>
      </Card>
    );

  const stages = board?.stages ?? [];
  const total = stages.reduce((n, s) => n + s.count, 0);
  const inTransit = stages
    .filter((s) => !["factory", "warehouse"].includes(s.id))
    .reduce((n, s) => n + s.count, 0);
  const atCustoms = stages.find((s) => s.id === "customs")?.count ?? 0;
  const received = stages.find((s) => s.id === "warehouse")?.count ?? 0;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-line bg-sunken px-4 py-3 text-xs text-muted">
        Панель информационная: показывает движение импортных поставок по событиям{" "}
        <span className="font-medium text-ink">import.*</span>. Приёмка на склад и остатки ведутся в WMS
        (закупка → склад) — здесь не дублируются.
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiTile label="Всего поставок" value={total} tone="ink" />
        <KpiTile label="В движении" value={inTransit} tone="brand" />
        <KpiTile label="На таможне" value={atCustoms} tone="amber" />
        <KpiTile label="Принято на склад" value={received} tone="emerald" sub="факт прихода (учёт — в WMS)" />
      </div>

      {total === 0 ? (
        <Card title="Цепочка импорта">
          <p className="py-6 text-center text-sm text-muted">
            Импортных поставок пока нет. Они появляются из заявок закупки и событий{" "}
            <span className="font-medium text-ink">import.*</span> — подключим по мере наполнения цепочки.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {stages.map((s) => (
              <span
                key={s.id}
                className="rounded-md bg-sunken px-2 py-1 text-[11px] text-muted"
                style={s.color ? { borderLeft: `3px solid ${s.color}` } : undefined}
              >
                {s.title}
              </span>
            ))}
          </div>
        </Card>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {stages.map((stage) => (
            <div key={stage.id} className="min-w-[240px] flex-1">
              <div className="mb-2 flex items-center justify-between gap-2 px-1">
                <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: stage.color || "#94A3B8" }} />
                  {stage.title}
                </span>
                <span className="text-xs text-muted">{stage.count}</span>
              </div>
              <div className="space-y-2">
                {stage.cards.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-[11px] text-faint">
                    пусто
                  </p>
                ) : (
                  stage.cards.map((card) => (
                    <div key={card.id} className="rounded-lg border border-line bg-surface p-3 shadow-card">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-ink">
                          {card.flag} {card.title}
                        </span>
                        {card.priority && (
                          <Pill text={card.priority} tone={PRIORITY_TONE[card.priority] ?? "slate"} />
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted">{card.subtitle}</div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
                        <span className="font-medium text-muted">{card.code}</span>
                        {card.status_tag && <Pill text={card.status_tag} tone="blue" />}
                        {card.amount != null && card.amount > 0 && (
                          <span className="tabular-nums text-money">{formatByn(card.amount)}</span>
                        )}
                      </div>
                      {card.tags && card.tags.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {card.tags.map((t, i) => (
                            <span key={i} className="rounded bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                      {(card.owner || card.date) && (
                        <div className="mt-1.5 flex items-center justify-between text-[10px] text-faint">
                          <span>{card.owner}</span>
                          <span>{card.date}</span>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
