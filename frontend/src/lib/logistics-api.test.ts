import { afterEach, describe, expect, it, vi } from "vitest";

import {
  awardRfq,
  broadcastRfq,
  createAuditEntry,
  createCarrier,
  fetchAudit,
  fetchBids,
  fetchCargoCapabilities,
  fetchCarriers,
  fetchCostInsights,
  fetchCosts,
  fetchDashboard,
  fetchEligible,
  fetchImportBoard,
  fetchImports,
  fetchImportsInTransit,
  fetchInvites,
  fetchRankedBids,
  fetchRecommendation,
  fetchRfq,
  fetchRfqs,
  fetchScorecard,
  fetchShipments,
  fetchTariffs,
  fetchVehicles,
  fetchZones,
  negotiateBid,
  patchImportStage,
  patchScorecardMetrics,
  patchShipmentStatus,
  patchShipmentTracking,
  patchTariff,
  recomputeScorecard,
  seedAudit,
  seedCarriers,
  seedFleet,
  seedRfq,
  seedScorecard,
  seedTariffs,
  seedZones,
} from "@/lib/logistics-api";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fetchMock = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubReject() {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net down")));
}

describe("logistics-api — доставка/дашборд", () => {
  it("fetchShipments дёргает верный URL, no-store, и возвращает данные", async () => {
    const fetchMock = stubFetch([{ id: 1, number: "SH-1" }]);
    const res = await fetchShipments();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/shipments", { cache: "no-store" });
    expect(res).toEqual([{ id: 1, number: "SH-1" }]);
  });

  it("fetchShipments → [] при ошибке сети и при !ok", async () => {
    stubReject();
    expect(await fetchShipments()).toEqual([]);
    stubFetch({}, false);
    expect(await fetchShipments()).toEqual([]);
  });

  it("fetchDashboard/fetchCosts → null-fallback", async () => {
    const fetchMock = stubFetch({ in_transit: 3 });
    expect((await fetchDashboard())?.in_transit).toBe(3);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/dashboard", { cache: "no-store" });

    stubReject();
    expect(await fetchDashboard()).toBeNull();
    expect(await fetchCosts()).toBeNull();
  });

  it("patchShipmentStatus шлёт PATCH с телом {status}", async () => {
    const fetchMock = stubFetch({ id: 5, status: "in_transit" });
    const res = await patchShipmentStatus(5, "in_transit");
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/shipments/5", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "in_transit" }),
    });
    expect(res?.status).toBe("in_transit");

    stubFetch({}, false);
    expect(await patchShipmentStatus(5, "in_transit")).toBeNull();
  });

  it("patchShipmentTracking шлёт весь patch-объект на /tracking", async () => {
    const fetchMock = stubFetch({ id: 5, tracking_status: "customs" });
    const patch = { tracking_status: "customs", eta: "2026-08-01", tracking_no: "TN1" };
    await patchShipmentTracking(5, patch);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/shipments/5/tracking", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  });
});

describe("logistics-api — импорт из Китая", () => {
  it("fetchImports / fetchImportBoard бьют по верным путям", async () => {
    const fetchMock = stubFetch([{ id: 1 }]);
    await fetchImports();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/imports", { cache: "no-store" });

    stubFetch({ stages: [] });
    const board = await fetchImportBoard();
    expect(board?.stages).toEqual([]);

    stubReject();
    expect(await fetchImports()).toEqual([]);
    expect(await fetchImportBoard()).toBeNull();
  });

  it("patchImportStage шлёт PATCH на /logistics/imports/:id", async () => {
    const fetchMock = stubFetch({ id: 3, stage: "customs" });
    const res = await patchImportStage(3, { stage: "customs", customs_status: "cleared" });
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/imports/3", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: "customs", customs_status: "cleared" }),
    });
    expect(res?.stage).toBe("customs");
  });

  it("fetchImportsInTransit возвращает список / [] при ошибке", async () => {
    const fetchMock = stubFetch([{ po_ref: "PO-1", cargo: "x", qty: 1, stage: "in_transit" }]);
    const res = await fetchImportsInTransit();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/imports/in-transit", { cache: "no-store" });
    expect(res[0].po_ref).toBe("PO-1");
    stubReject();
    expect(await fetchImportsInTransit()).toEqual([]);
  });
});

describe("logistics-api — тарифы/зоны", () => {
  it("fetchZones/seedZones бьют по верным путям и методам", async () => {
    const fetchMock = stubFetch([{ id: 1, code: "MSK" }]);
    await fetchZones();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/zones", { cache: "no-store" });

    const seedMock = stubFetch([{ id: 1, code: "MSK" }]);
    await seedZones();
    expect(seedMock).toHaveBeenCalledWith("/api/logistics/zones/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
  });

  it("fetchTariffs кодирует zone-параметр в query", async () => {
    const fetchMock = stubFetch([{ carrier_code: "DPD" }]);
    await fetchTariffs("Минск Центр");
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carrier-tariffs?zone=${encodeURIComponent("Минск Центр")}`,
      { cache: "no-store" },
    );
  });

  it("seedTariffs — POST без тела", async () => {
    const fetchMock = stubFetch([]);
    await seedTariffs();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/carrier-tariffs/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
  });

  it("patchTariff кодирует carrier/zone в пути и шлёт patch-тело", async () => {
    const fetchMock = stubFetch({ carrier_code: "DPD", zone_code: "MSK/1" });
    const patch = { price_w5: 10.5, pickup_fee: 2 };
    await patchTariff("DPD X", "MSK/1", patch);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carrier-tariffs/${encodeURIComponent("DPD X")}/${encodeURIComponent("MSK/1")}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      },
    );

    stubFetch({}, false);
    expect(await patchTariff("DPD", "MSK", patch)).toBeNull();
  });
});

describe("logistics-api — перевозчики/парк", () => {
  it("fetchCarriers/seedCarriers/seedFleet", async () => {
    const fetchMock = stubFetch([{ id: 1, code: "DPD" }]);
    await fetchCarriers();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/carriers", { cache: "no-store" });

    const seedMock = stubFetch([{ id: 1 }]);
    await seedCarriers();
    expect(seedMock).toHaveBeenCalledWith("/api/logistics/carriers/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });

    const fleetMock = stubFetch(null);
    await seedFleet();
    expect(fleetMock).toHaveBeenCalledWith("/api/logistics/fleet/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
  });

  it("createCarrier шлёт payload как JSON-тело POST", async () => {
    const fetchMock = stubFetch({ id: 9, code: "NEW" });
    const payload = { name: "Новый перевозчик", code: "NEW", kind: "3pl" };
    const res = await createCarrier(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/carriers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    expect(res?.code).toBe("NEW");

    stubFetch({}, false);
    expect(await createCarrier(payload)).toBeNull();
  });

  it("fetchVehicles/fetchCargoCapabilities кодируют код перевозчика в пути", async () => {
    const fetchMock = stubFetch([{ vehicle_class: "фура" }]);
    await fetchVehicles("DPD/1");
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carriers/${encodeURIComponent("DPD/1")}/vehicles`,
      { cache: "no-store" },
    );

    const capsMock = stubFetch([{ category: "adr" }]);
    await fetchCargoCapabilities("DPD/1");
    expect(capsMock).toHaveBeenCalledWith(
      `/api/logistics/carriers/${encodeURIComponent("DPD/1")}/cargo-capabilities`,
      { cache: "no-store" },
    );
  });

  it("fetchEligible строит query только из заданных полей (полный набор)", async () => {
    const fetchMock = stubFetch([{ carrier_code: "DPD" }]);
    await fetchEligible({ weight_kg: 12.5, category: "хрупкое", needs_temp: true, max_dim_cm: 200, adr: true });
    const params = new URLSearchParams({
      weight_kg: "12.5",
      category: "хрупкое",
      needs_temp: "true",
      max_dim_cm: "200",
      adr: "true",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carriers/eligible?${params.toString()}`,
      { cache: "no-store" },
    );
  });

  it("fetchEligible пропускает falsy/undefined поля (needs_temp:false, adr отсутствует)", async () => {
    const fetchMock = stubFetch([]);
    await fetchEligible({ category: "обычное", needs_temp: false });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/logistics/carriers/eligible?category=%D0%BE%D0%B1%D1%8B%D1%87%D0%BD%D0%BE%D0%B5",
      { cache: "no-store" },
    );
  });

  it("fetchEligible с пустым запросом даёт пустую query-строку", async () => {
    const fetchMock = stubFetch([]);
    await fetchEligible({});
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/carriers/eligible?", { cache: "no-store" });
  });
});

describe("logistics-api — scorecard", () => {
  it("fetchScorecard кодирует period в query", async () => {
    const fetchMock = stubFetch([{ carrier_code: "DPD", score: 88 }]);
    const res = await fetchScorecard("2026-Q3");
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carriers/scorecard?period=${encodeURIComponent("2026-Q3")}`,
      { cache: "no-store" },
    );
    expect(res[0].score).toBe(88);
  });

  it("seedScorecard/recomputeScorecard — POST без тела", async () => {
    const seedMock = stubFetch([]);
    await seedScorecard();
    expect(seedMock).toHaveBeenCalledWith("/api/logistics/carriers/scorecard/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });

    const recomputeMock = stubFetch([]);
    await recomputeScorecard();
    expect(recomputeMock).toHaveBeenCalledWith("/api/logistics/carriers/scorecard/recompute", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
  });

  it("patchScorecardMetrics кодирует carrier+period и шлёт тело", async () => {
    const fetchMock = stubFetch({ carrier_code: "DPD X", period: "2026/Q3", score: 90 });
    const patch = { otd_pct: 95.5, shipments: 40 };
    const res = await patchScorecardMetrics("DPD X", "2026/Q3", patch);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/logistics/carriers/scorecard/${encodeURIComponent("DPD X")}?period=${encodeURIComponent("2026/Q3")}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      },
    );
    expect(res?.score).toBe(90);
  });
});

describe("logistics-api — аудит счетов", () => {
  it("fetchAudit кодирует period, seedAudit — POST без тела", async () => {
    const fetchMock = stubFetch({ period: "2026-07", checked: 10, discrepancies: 2, to_recover: 500, items: [] });
    const res = await fetchAudit("2026-07");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/logistics/costs/audit?period=2026-07",
      { cache: "no-store" },
    );
    expect(res?.to_recover).toBe(500);

    const seedMock = stubFetch([]);
    await seedAudit();
    expect(seedMock).toHaveBeenCalledWith("/api/logistics/costs/audit/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });

    stubReject();
    expect(await fetchAudit("2026-07")).toBeNull();
  });

  it("createAuditEntry шлёт payload как JSON и маппит variance>0 ответ", async () => {
    const fetchMock = stubFetch({
      id: 1, shipment_code: "SH-1", carrier_code: "DPD", invoice_amount: 600,
      expected_amount: 500, variance: 100, reason: "перевес", status: "flagged",
    });
    const payload = { shipment_code: "SH-1", carrier_code: "DPD", invoice_amount: 600, zone_code: "MSK", weight_kg: 10 };
    const res = await createAuditEntry(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/costs/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    expect(res?.variance).toBe(100);

    stubFetch({}, false);
    expect(await createAuditEntry(payload)).toBeNull();
  });
});

describe("logistics-api — тендер (RFQ)", () => {
  it("fetchRfqs/fetchRfq/fetchInvites/fetchBids/fetchRankedBids/fetchRecommendation — верные пути", async () => {
    const fetchMock = stubFetch([{ id: 1, number: "RFQ-1" }]);
    await fetchRfqs();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/rfqs", { cache: "no-store" });

    stubFetch({ id: 1, number: "RFQ-1" });
    const rfq = await fetchRfq(1);
    expect(rfq?.number).toBe("RFQ-1");

    const invitesMock = stubFetch([{ id: 1, rfq_id: 1, carrier_code: "DPD", channel: "email", status: "sent" }]);
    await fetchInvites(1);
    expect(invitesMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/invites", { cache: "no-store" });

    const bidsMock = stubFetch([{ id: 1, rfq_id: 1 }]);
    await fetchBids(1);
    expect(bidsMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/bids", { cache: "no-store" });

    const rankedMock = stubFetch([{ id: 1, rfq_id: 1, is_best_value: true }]);
    const ranked = await fetchRankedBids(1);
    expect(rankedMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/bids/ranked", { cache: "no-store" });
    expect(ranked[0].is_best_value).toBe(true);

    const recMock = stubFetch({ cheapest: {}, best_value: {}, reliability_premium: 50, same_carrier: false, rationale: "r" });
    const rec = await fetchRecommendation(1);
    expect(recMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/recommendation", { cache: "no-store" });
    expect(rec?.reliability_premium).toBe(50);
  });

  it("fetchRfq → null при ошибке", async () => {
    stubReject();
    expect(await fetchRfq(1)).toBeNull();
    expect(await fetchRecommendation(1)).toBeNull();
  });

  it("seedRfq — POST без тела", async () => {
    const fetchMock = stubFetch({ id: 1, number: "RFQ-SEED" });
    const res = await seedRfq();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/rfqs/seed", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
    expect(res?.number).toBe("RFQ-SEED");
  });

  it("broadcastRfq — POST без тела на /broadcast", async () => {
    const fetchMock = stubFetch({ rfq_id: 1, status: "broadcast", invited: 3, carriers: ["DPD"] });
    const res = await broadcastRfq(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/broadcast", {
      method: "POST",
      headers: undefined,
      body: undefined,
    });
    expect(res?.invited).toBe(3);
  });

  it("negotiateBid шлёт carrier_code/new_price/comment; comment по умолчанию ''", async () => {
    const fetchMock = stubFetch({ id: 2, rfq_id: 1, round: 2 });
    await negotiateBid(1, "DPD", 950.5);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/negotiate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ carrier_code: "DPD", new_price: 950.5, comment: "" }),
    });

    const fetchMock2 = stubFetch({ id: 3, rfq_id: 1, round: 3 });
    await negotiateBid(1, "DPD", 900, "финальная цена");
    expect(fetchMock2).toHaveBeenCalledWith("/api/logistics/rfqs/1/negotiate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ carrier_code: "DPD", new_price: 900, comment: "финальная цена" }),
    });
  });

  it("awardRfq: с carrierCode шлёт {carrier_code}, без — {strategy} (дефолт cheapest)", async () => {
    const fetchMock = stubFetch({ rfq_id: 1, status: "awarded", carrier_code: "DPD" });
    await awardRfq(1, "DPD");
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/rfqs/1/award", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ carrier_code: "DPD" }),
    });

    const fetchMock2 = stubFetch({ rfq_id: 1, status: "awarded" });
    await awardRfq(1);
    expect(fetchMock2).toHaveBeenCalledWith("/api/logistics/rfqs/1/award", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy: "cheapest" }),
    });

    const fetchMock3 = stubFetch({ rfq_id: 1, status: "awarded" });
    await awardRfq(1, undefined, "best_value");
    expect(fetchMock3).toHaveBeenCalledWith("/api/logistics/rfqs/1/award", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy: "best_value" }),
    });

    stubFetch({}, false);
    expect(await awardRfq(1)).toBeNull();
  });
});

describe("logistics-api — аналитика стоимости", () => {
  it("fetchCostInsights использует дефолт weight_kg=30", async () => {
    const fetchMock = stubFetch({ reference_weight_kg: 30, zones: [], potential_savings: 0 });
    const res = await fetchCostInsights();
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/cost-insights?weight_kg=30", { cache: "no-store" });
    expect(res?.reference_weight_kg).toBe(30);
  });

  it("fetchCostInsights принимает произвольный weight_kg и возвращает null при ошибке", async () => {
    const fetchMock = stubFetch({ reference_weight_kg: 50 });
    await fetchCostInsights(50);
    expect(fetchMock).toHaveBeenCalledWith("/api/logistics/cost-insights?weight_kg=50", { cache: "no-store" });

    stubReject();
    expect(await fetchCostInsights()).toBeNull();
  });
});
