"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { bestBid, bidSavings, rankBids, rfqStatusLabel } from "@/lib/logistics-domain";
import {
  awardRfq,
  broadcastRfq,
  fetchBids,
  fetchInvites,
  fetchRfqs,
  seedRfq,
  type Bid,
  type Invite,
  type Rfq,
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
  const [bids, setBids] = useState<Bid[]>([]);

  async function loadRfqs() {
    const list = await fetchRfqs();
    setRfqs(list);
    setLoading(false);
    return list;
  }

  useEffect(() => {
    void loadRfqs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openRfq(id: number) {
    setSelected(id);
    const [inv, bd] = await Promise.all([fetchInvites(id), fetchBids(id)]);
    setInvites(inv);
    setBids(bd);
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
    await broadcastRfq(selected);
    await openRfq(selected);
    await loadRfqs();
    setBusy(false);
  }

  async function onAward() {
    if (selected == null) return;
    setBusy(true);
    const best = bestBid(bids);
    await awardRfq(selected, best?.carrier_code);
    await openRfq(selected);
    await loadRfqs();
    setBusy(false);
  }

  if (loading) return <Loading />;
  if (rfqs.length === 0)
    return <EmptyState text="Тендеров (RFQ) пока нет." onSeed={onSeed} seedLabel="Создать демо-тендер" busy={busy} />;

  const ranked = rankBids(bids);
  const best = bestBid(bids);
  const savings = bidSavings(bids);
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
                (r.id === selected ? "border-brand bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50")
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
            <div className="flex gap-2">
              <GhostButton onClick={onBroadcast} busy={busy}>Разослать</GhostButton>
              <button
                onClick={onAward}
                disabled={busy || !best}
                className="rounded-lg bg-brand px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
              >
                Присудить лучшему
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
              <div className="mb-3 flex flex-wrap gap-4 text-sm">
                {best && (
                  <span>
                    Лучшая: <span className="font-semibold text-ink">{best.carrier}</span> ·{" "}
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
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="border-b border-slate-100 text-left text-xs text-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">Перевозчик</th>
                      <th className="px-3 py-2 text-right font-medium">Цена</th>
                      <th className="px-3 py-2 text-right font-medium">Срок</th>
                      <th className="px-3 py-2 font-medium">ТС</th>
                      <th className="px-3 py-2 text-right font-medium">Раунд</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((b) => {
                      const isBest = best != null && b.carrier_code === best.carrier_code && b.price === best.price;
                      return (
                        <tr
                          key={b.id}
                          className={
                            "border-b border-slate-50 last:border-0 " + (isBest ? "bg-emerald-50/50" : "")
                          }
                        >
                          <td className="px-3 py-2">
                            <span className="flex items-center gap-2 font-medium text-ink">
                              {b.carrier}
                              {isBest && <Pill text="лучшая" tone="emerald" />}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">{formatByn(b.price)}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-slate-600">{b.eta_days} дн</td>
                          <td className="px-3 py-2 text-slate-600">{b.vehicle_class}</td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted">{b.round}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
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
