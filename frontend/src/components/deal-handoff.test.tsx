import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DealHandoffBlock } from "@/components/deal-handoff";
import type { DealHandoff } from "@/lib/api";

// Компонент сам ходит в GET /api/sales/deals/{id}/handoff через глобальный fetch
// (fetchDealHandoff в @/lib/api) — мокаем fetch напрямую, провайдер валюты не нужен
// (дефолт CurrencyContext = formatMoney).
function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}
function jsonOk(data: DealHandoff | null): () => Promise<Response> {
  return () => Promise.resolve({ ok: true, json: () => Promise.resolve(data) } as Response);
}

function handoffFixture(over: Partial<DealHandoff> = {}): DealHandoff {
  return {
    deal_id: 1,
    number: "D-1",
    counterparty: "ООО Ромашка",
    amount: 150000,
    owner: "Иванов И.И.",
    funnel: "sales",
    items: [{ sku_code: "SKU-1", title: "Товар 1", qty: 3 }],
    gross_profit: 45000,
    handed_off_at: "2026-07-10T12:00:00Z",
    ...over,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("DealHandoffBlock", () => {
  it("до ответа сервера и когда handoff ещё нет (null) — ничего не рендерит (honest-empty)", async () => {
    stubFetch(jsonOk(null));
    const { container } = render(<DealHandoffBlock dealId="1" />);
    expect(container).toBeEmptyDOMElement();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByText("Передано в исполнение")).not.toBeInTheDocument();
  });

  it("ошибка сервера (ok=false → fetchDealHandoff вернёт null) — блок не показываем", async () => {
    stubFetch(() => Promise.resolve({ ok: false, status: 500 } as Response));
    render(<DealHandoffBlock dealId="1" />);
    await waitFor(() =>
      expect(screen.queryByText("Передано в исполнение")).not.toBeInTheDocument(),
    );
  });

  it("готовые данные — сумма, валовая прибыль, ответственный и число позиций из ответа", async () => {
    stubFetch(jsonOk(handoffFixture()));
    render(<DealHandoffBlock dealId="1" />);
    expect(await screen.findByText("Передано в исполнение")).toBeInTheDocument();
    expect(screen.getByText(/150.?000/)).toBeInTheDocument();
    expect(screen.getByText(/45.?000/)).toBeInTheDocument();
    expect(screen.getByText("Иванов И.И.")).toBeInTheDocument();
    // «Позиций» — счётчик items.length
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("SKU-1")).toBeInTheDocument();
    expect(screen.getByText(/Товар 1/)).toBeInTheDocument();
    expect(screen.getByText("× 3")).toBeInTheDocument();
  });

  it("handed_off_at отрисован датой-временем; при null — блок с датой скрыт", async () => {
    stubFetch(jsonOk(handoffFixture({ handed_off_at: null })));
    render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    const expected = new Date("2026-07-10T12:00:00Z").toLocaleString("ru-RU");
    expect(screen.queryByText(expected)).not.toBeInTheDocument();
  });

  it("gross_profit=null — прочерк «—» вместо выдуманной прибыли", async () => {
    stubFetch(jsonOk(handoffFixture({ gross_profit: null })));
    render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    const label = screen.getByText("Валовая прибыль");
    expect(label.parentElement?.textContent).toContain("—");
  });

  it("owner пустая строка — «Ответственный» показан как прочерк «—»", async () => {
    stubFetch(jsonOk(handoffFixture({ owner: "" })));
    render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    const label = screen.getByText("Ответственный");
    expect(label.parentElement?.textContent).toContain("—");
  });

  it("items пустой массив — «Позиций нет», список не рендерится", async () => {
    stubFetch(jsonOk(handoffFixture({ items: [] })));
    render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    expect(
      screen.getByText(/Позиций нет — handoff передаёт только сводку сделки/),
    ).toBeInTheDocument();
    expect(screen.queryByText("SKU-1")).not.toBeInTheDocument();
  });

  it("несколько позиций — «Позиций» считает их количество, а не первую строку", async () => {
    stubFetch(
      jsonOk(
        handoffFixture({
          items: [
            { sku_code: "A", title: "Товар А", qty: 1 },
            { sku_code: "B", title: "Товар Б", qty: 2 },
          ],
        }),
      ),
    );
    render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    const label = screen.getByText("Позиций");
    expect(label.parentElement?.textContent).toContain("2");
    expect(screen.getByText("× 1")).toBeInTheDocument();
    expect(screen.getByText("× 2")).toBeInTheDocument();
  });

  it("смена dealId запрашивает handoff по новому id (эффект зависит от dealId)", async () => {
    const fetchMock = vi.fn(jsonOk(handoffFixture({ deal_id: 2, number: "D-2" })));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<DealHandoffBlock dealId="1" />);
    await screen.findByText("Передано в исполнение");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sales/deals/1/handoff",
      expect.objectContaining({ cache: "no-store" }),
    );
    rerender(<DealHandoffBlock dealId="2" />);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/sales/deals/2/handoff",
        expect.objectContaining({ cache: "no-store" }),
      ),
    );
  });
});
