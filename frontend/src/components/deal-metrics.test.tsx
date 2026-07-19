import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DealMetrics } from "@/components/deal-metrics";
import type { DealMargin, MarginLine } from "@/lib/margin";

// Компонент сам ходит в GET /api/sales/deals/{id}/margin через глобальный fetch —
// мокаем его пофичево (fmt по умолчанию = formatMoney, провайдер валюты не нужен).
function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}
function jsonOk(data: DealMargin): () => Promise<Response> {
  return () => Promise.resolve({ ok: true, json: () => Promise.resolve(data) } as Response);
}

function marginLine(over: Partial<MarginLine> = {}): MarginLine {
  return {
    sku_code: "S1",
    title: "Товар",
    qty: 1,
    unit_price: 100,
    revenue: 100,
    unit_landed_cost: 60,
    cogs: 60,
    margin_pct: 40,
    status: "priced",
    cost_shipment_id: null,
    cost_fixed_at: null,
    cost_fx_rate: null,
    cost_source: "onec",
    price_source: "quote",
    ...over,
  };
}

function marginFixture(over: Partial<DealMargin> = {}): DealMargin {
  return {
    deal_id: 1,
    revenue: 1000,
    cogs_landed: 600,
    gross_profit: 400,
    margin_pct: 40,
    priced_count: 1,
    total_count: 1,
    reason: null,
    lines: [marginLine()],
    ...over,
  };
}

// Текст ячейки метрики = «Подпись» + «Значение» (соседние div в одной ячейке).
function cellText(label: string): string {
  return screen.getByText(label).parentElement?.textContent ?? "";
}

afterEach(() => vi.unstubAllGlobals());

const BASE = { dealId: "1", amount: 1000, closeDate: "2026-08-01" };

describe("DealMetrics", () => {
  it("до ответа сервера — Сумма показана, а себестоимость в состоянии загрузки «…»", () => {
    stubFetch(() => new Promise<Response>(() => {})); // фетч висит → status=loading
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(cellText("Сумма")).toContain("₽"); // сумма из пропса, не ждёт сервера
    expect(cellText("Себестоимость")).toContain("…"); // прочерк-загрузка, не «—»
    expect(cellText("Прибыль")).toContain("…");
  });

  it("ошибка сервера — предупреждение и прочерк «—» вместо выдуманных денег", async () => {
    stubFetch(() => Promise.resolve({ ok: false, status: 500 } as Response));
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(
      await screen.findByText(/Не удалось рассчитать маржу/),
    ).toBeInTheDocument();
    expect(cellText("Себестоимость")).toContain("—");
    expect(cellText("Себестоимость")).not.toContain("…");
  });

  it("готовые данные — себестоимость, прибыль и маржа берутся из ответа сервера", async () => {
    stubFetch(jsonOk(marginFixture({ cogs_landed: 600, gross_profit: 400, margin_pct: 40 })));
    render(<DealMetrics {...BASE} stageId="meeting" />);
    await waitFor(() => expect(cellText("Себестоимость")).toContain("600"));
    expect(cellText("Прибыль")).toContain("400");
    expect(cellText("Маржа")).toContain("40%");
  });

  it("вероятность и взвешенный прогноз считаются по стадии; прогноз = сумма×вероятность", async () => {
    stubFetch(jsonOk(marginFixture()));
    render(<DealMetrics {...BASE} amount={1000} stageId="meeting" />);
    // stageId=meeting → дефолт STAGE_PROBABILITY = 55%
    await waitFor(() => expect(cellText("Вероятность")).toContain("55%"));
    // взвеш. прогноз = 1000 × 55 / 100 = 550
    expect(cellText("Взвеш. прогноз")).toContain("550");
  });

  it("явная вероятность сделки переопределяет дефолт стадии", async () => {
    stubFetch(jsonOk(marginFixture()));
    render(<DealMetrics {...BASE} amount={200} stageId="new" probability={90} />);
    // override 90% выигрывает у дефолта стадии new (10%)
    await waitFor(() => expect(cellText("Вероятность")).toContain("90%"));
    expect(cellText("Вероятность")).not.toContain("10%");
    // взвеш. = 200 × 90 / 100 = 180
    expect(cellText("Взвеш. прогноз")).toContain("180");
  });

  it("частичная оценка — бейдж «оценка по N из M позиций»", async () => {
    stubFetch(
      jsonOk(
        marginFixture({
          priced_count: 2,
          total_count: 5,
          lines: [marginLine(), marginLine({ sku_code: "S2" })],
        }),
      ),
    );
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(await screen.findByText(/оценка по 2 из 5 позиций/)).toBeInTheDocument();
  });

  it("источник себес landed — бейдж «из закупок» с номером партии и курсом", async () => {
    stubFetch(
      jsonOk(
        marginFixture({
          lines: [marginLine({ cost_source: "landed", cost_shipment_id: 77, cost_fx_rate: 3.2 })],
        }),
      ),
    );
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(await screen.findByText(/себес · из закупок/)).toBeInTheDocument();
    expect(screen.getByText(/партия #77/)).toBeInTheDocument();
    expect(screen.getByText(/курс 3\.2/)).toBeInTheDocument();
  });

  it("разные источники себес — «смешанный источник», без ложной детали партии", async () => {
    stubFetch(
      jsonOk(
        marginFixture({
          priced_count: 2,
          total_count: 2,
          lines: [
            marginLine({ sku_code: "A", cost_source: "onec" }),
            marginLine({ sku_code: "B", cost_source: "landed", cost_shipment_id: 88 }),
          ],
        }),
      ),
    );
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(await screen.findByText(/смешанный источник/)).toBeInTheDocument();
    // при смешанных источниках деталь landed-партии показывать нельзя (ложный провенанс денег)
    expect(screen.queryByText(/партия #88/)).not.toBeInTheDocument();
  });

  it("цена из прайса 1С — предупреждение о несогласованной с клиентом цене", async () => {
    stubFetch(
      jsonOk(marginFixture({ lines: [marginLine({ price_source: "onec" })] })),
    );
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(await screen.findByText(/цена · прайс 1С/)).toBeInTheDocument();
    expect(screen.getByText(/не согласована с клиентом/)).toBeInTheDocument();
  });

  it("honest reason — подсказка про «Закупки», когда себес не рассчитан", async () => {
    stubFetch(
      jsonOk(
        marginFixture({
          cogs_landed: null,
          gross_profit: null,
          margin_pct: null,
          priced_count: 0,
          reason: "себестоимость закупок не рассчитана",
          lines: [marginLine({ status: "no_cost", cost_source: null })],
        }),
      ),
    );
    render(<DealMetrics {...BASE} stageId="meeting" />);
    expect(
      await screen.findByText(/себестоимость закупок не рассчитана/),
    ).toBeInTheDocument();
    // денег не выдумываем — себес остаётся прочерком
    expect(cellText("Себестоимость")).toContain("—");
  });
});
