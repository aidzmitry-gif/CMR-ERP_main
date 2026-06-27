"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { bestBid, bidSavings, rfqStatusLabel } from "@/lib/logistics-domain";
import {
  awardRfq,
  broadcastRfq,
  fetchInvites,
  fetchRankedBids,
  fetchRecommendation,
  fetchRfqs,
  seedRfq,
  type AwardStrategy,
  type Bid,
  type BroadcastResult,
  type Invite,
  type Rfq,
  type TenderRecommendation,
} from "@/lib/logistics-api";
import { formatByn, formatNumber } from "@/lib/format";

const STATUS_TONE: Record<string, "slate" | "blue" | "emerald" | "amber" | "violet"> = {
  draft: "slate",
  sent: "blue",
  collecting: "blue",
  negotiation: "amber",
  awarded: "emerald",
  contracted: "violet",
};

export function LogisticsTender() {
  const [rfqs, setRfqs] = useState<Rfq[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<number | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [bids, setBids] = useState<Bid[]>([]);          // best-fit порядок (из /bids/ranked)
  const [recommendation, setRecommendation] = useState<TenderRecommendation | null>(null);
  const [lastBroadcast, setLastBroadcast] = useState<BroadcastResult | null>(null);

  async function loadRfqs() {
    const list = await fetchRfqs();
    setRfqs(list);
    setLoading(false);
    return list;
  }

  useEffect(() => {
    void fetchRfqs().then((list) => {
      setRfqs(list);
      setLoading(false);
    });
  }, []);

  async function openRfq(id: number) {
    setSelected(id);
    const [inv, bd, rec] = await Promise.all([
      fetchInvites(id),
      fetchRankedBids(id),
      fetchRecommendation(id),
    ]);
    setInvites(inv);
    setBids(bd);
    setRecommendation(rec);
  }

  async function onSeed() {
    setBusy(true);
    const rfq = await seedRfq();
    const list = await loadRfqs();
    const target = rfq?.id ?? list[0]?.id;
    if (target) await openRfq(target);
    setBusy(false);
  }

  async function onBroadcast() {
    if (selected == null) return;
    setBusy(true);
    const res = await broadcastRfq(selected);
    await openRfq(selected);
    await loadRfqs();
    setLastBroadcast(res);
    setBusy(false);
  }

  async function onAward(strategy: AwardStrategy) {
    if (selected == null) return;
    setBusy(true);
    await awardRfq(selected, undefined, strategy);
    await openRfq(selected);
    await loadRfqs();
    setBusy(false);
  }

  if (loading) return <Loading />;
  if (rfqs.length === 0)
    return <EmptyState text="Тендеров (RFQ) пока нет." onSeed={onSeed} seedLabel="Создать демо-тендер" busy={busy} />;

  // bids уже отсортированы best-fit (цена↔качество) бэкендом; best = самый дешёвый (для экономии).
  const best = bestBid(bids);
  const savings = bidSavings(bids);
  const hasQuality = bids.some((b) => (b.value_score ?? 0) > 0);
  const current = rfqs.find((r) => r.id === selected) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <Card
        title="Тендеры (RFQ)"
        action={<GhostButton onClick={onSeed} busy={busy}>Демо-тендер</GhostButton>}
      >
        <div className="space-y-2">
          {rfqs.map((r) => (
            <button
              key={r.id}
              onClick={() => openRfq(r.id)}
              className={
                "block w-full rounded-lg border px-3 py-2.5 text-left text-sm " +
                (r.id === selected ? "border-accent bg-blue-50" : "border-line bg-surface hover:bg-sunken")
              }
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-ink">{r.number}</span>
                <Pill text={rfqStatusLabel(r.status)} tone={STATUS_TONE[r.status] ?? "slate"} />
              </div>
              <div className="mt-0.5 text-xs text-muted">
                {r.cargo} · {formatNumber(r.weight_kg)} кг · {r.route_from} → {r.route_to}
              </div>
              {r.awarded_carrier_code && r.awarded_price != null && (
                <div className="mt-1 text-xs text-emerald-600">
                  Победитель: {r.awarded_carrier_code} · {formatByn(r.awarded_price)}
                </div>
              )}
            </button>
          ))}
        </div>
      </Card>

      {current ? (
        <Card
          title={`Ставки · ${current.number}`}
          hint={`${rfqStatusLabel(current.status)} · приглашено ${invites.length}`}
          action={
            <div className="flex flex-wrap gap-2">
              <GhostButton onClick={onBroadcast} busy={busy}>Разослать</GhostButton>
              <button
                onClick={() => onAward("cheapest")}
                disabled={busy || !best}
                title="Присудить самому дешёвому предложению"
                className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
              >
                По цене
              </button>
              <button
                onClick={() => onAward("best_value")}
                disabled={busy || !best}
                title="Присудить по соотношению цена↔качество (best-fit по scorecard)"
                className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
              >
                По соотношению
              </button>
            </div>
          }
        >
          {bids.length === 0 ? (
            <p className="py-4 text-sm text-muted">
              Ставок ещё нет. «Разослать» отправит запрос приглашённым перевозчикам.
            </p>
          ) : (
            <>
              {recommendation && (
                <div className="mb-3 rounded-lg border border-accent-soft bg-accent-soft/40 p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <Pill text="Рекомендация" tone="violet" />
                    <span className="text-xs text-muted">почему этот перевозчик</span>
                  </div>
                  <p className="text-sm text-ink">{recommendation.rationale}</p>
                  {!recommendation.same_carrier && (
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded-md border border-line bg-surface px-2.5 py-1.5">
                        <div className="text-muted">Дешевле всех</div>
                        <div className="font-semibold text-ink">{recommendation.cheapest.carrier}</div>
                        <div className="tabular-nums text-ink">{formatByn(recommendation.cheapest.price)}</div>
                      </div>
                      <div className="rounded-md border border-accent bg-surface px-2.5 py-1.5">
                        <div className="text-accent-ink">Надёжнее (best-fit)</div>
                        <div className="font-semibold text-ink">{recommendation.best_value.carrier}</div>
                        <div className="tabular-nums text-ink">
                          {formatByn(recommendation.best_value.price)}
                          {recommendation.reliability_premium > 0 && (
                            <span className="ml-1 text-faint">
                              (+{formatByn(recommendation.reliability_premium)} за надёжность)
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
              <div className="mb-3 flex flex-wrap gap-4 text-sm">
                {best && (
                  <span>
                    Дешевле всех: <span className="font-semibold text-ink">{best.carrier}</span> ·{" "}
                    <span className="font-semibold text-emerald-600">{formatByn(best.price)}</span>
                  </span>
                )}
                {savings > 0 && (
                  <span className="text-muted">
                    Экономия от конкуренции: <span className="font-semibold text-emerald-600">{formatByn(savings)}</span>
                  </span>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-sm">
                  <thead className="border-b border-line text-left text-xs text-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">Перевозчик</th>
                      <th className="px-3 py-2 text-right font-medium">Цена</th>
                      <th className="px-3 py-2 text-right font-medium">Срок</th>
                      <th className="px-3 py-2 font-medium">ТС</th>
                      <th className="px-3 py-2 text-right font-medium" title="Соотношение цена↔качество, 0–100">
                        Соотн.
                      </th>
                      <th className="px-3 py-2 text-right font-medium">Раунд</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bids.map((b) => {
                      const isCheapest = best != null && b.carrier_code === best.carrier_code && b.price === best.price;
                      return (
                        <tr
                          key={b.id}
                          className={
                            "border-b border-line last:border-0 " + (b.is_best_value ? "bg-accent-soft/40" : "")
                          }
                        >
                          <td className="px-3 py-2">
                            <span className="flex flex-wrap items-center gap-1.5 font-medium text-ink">
                              {b.carrier}
                              {b.is_best_value && <Pill text="по соотношению" tone="violet" />}
                              {isCheapest && <Pill text="дешевле" tone="emerald" />}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">{formatByn(b.price)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted">{b.eta_days} дн</td>
                          <td className="px-3 py-2 text-muted">{b.vehicle_class}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted">
                            {b.value_score != null ? Math.round(b.value_score * 100) : "—"}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted">{b.round}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!hasQuality && (
                <p className="mt-2 text-xs text-faint">
                  Соотношение нейтрально: нет данных scorecard за период — заполните вкладку «Scorecard».
                </p>
              )}
            </>
          )}

          {invites.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-muted">Рассылка приглашений</span>
                {lastBroadcast && (
                  <span className="text-xs text-emerald-600">
                    уведомлено {lastBroadcast.notified ?? 0} из {lastBroadcast.invited}
                  </span>
                )}
              </div>
              <div className="space-y-1">
                {invites.map((inv) => (
                  <div key={inv.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-muted">{inv.carrier_code}</span>
                    <div className="flex items-center gap-1.5">
                      <Pill text={inv.channel} tone={inv.channel === "none" ? "slate" : "blue"} />
                      <Pill
                        text={inv.status}
                        tone={inv.status === "responded" ? "emerald" : inv.status === "sent" ? "blue" : "slate"}
                      />
                      {inv.token && <span className="text-faint" title="публичная ссылка на ставку">ссылка …{inv.token.slice(-6)}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      ) : (
        <Card title="Ставки">
          <p className="py-4 text-sm text-muted">Выберите тендер слева, чтобы увидеть приглашения и ставки.</p>
        </Card>
      )}
    </div>
  );
}
