import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Тестируем компонент изолированно: сетевой слой '@/lib/logistics-api' — мок (возвращаем
// фикстуры). Доменную логику ('@/lib/logistics-domain': bestBid/bidSavings/rfqStatusLabel)
// и форматирование ('@/lib/format': formatByn/formatNumber) НЕ мокаем — проверяем реальный
// текст (деньги в BYN, русские подписи статусов) на выходе компонента.
vi.mock("@/lib/logistics-api", () => ({
  fetchRfqs: vi.fn(),
  fetchInvites: vi.fn(),
  fetchRankedBids: vi.fn(),
  fetchRecommendation: vi.fn(),
  seedRfq: vi.fn(),
  broadcastRfq: vi.fn(),
  awardRfq: vi.fn(),
  negotiateBid: vi.fn(),
}));

import { LogisticsTender } from "@/components/erp/logistics-tender";
import * as api from "@/lib/logistics-api";
import type { Bid, Invite, Rfq } from "@/lib/logistics-api";

const rfq: Rfq = {
  id: 1,
  number: "RFQ-001",
  cargo: "Сталь листовая",
  weight_kg: 500,
  category: "general",
  route_from: "Минск",
  route_to: "Брест",
  zone_code: "z-west",
  status: "collecting",
};

// best-fit порядок (как отдаёт /bids/ranked): ALFA дешевле И best_value; BETA дороже, но быстрее.
const bids: Bid[] = [
  {
    id: 10,
    rfq_id: 1,
    carrier_code: "ALFA",
    carrier: "Альфа Транс",
    price: 800,
    eta_days: 3,
    vehicle_class: "тент",
    round: 1,
    is_best: false,
    value_score: 0.9,
    is_best_value: true,
  },
  {
    id: 11,
    rfq_id: 1,
    carrier_code: "BETA",
    carrier: "Бета Логистик",
    price: 950,
    eta_days: 2,
    vehicle_class: "рефрижератор",
    round: 1,
    is_best: false,
    value_score: 0.7,
  },
];

const invites: Invite[] = [
  { id: 1, rfq_id: 1, carrier_code: "ALFA", channel: "email", status: "sent" },
  { id: 2, rfq_id: 1, carrier_code: "BETA", channel: "none", status: "invited" },
];

const m = <T,>(fn: T) => fn as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // дефолты: список из одного RFQ, деталь пустая — тесты переопределяют по месту.
  m(api.fetchRfqs).mockResolvedValue([rfq]);
  m(api.fetchInvites).mockResolvedValue([]);
  m(api.fetchRankedBids).mockResolvedValue([]);
  m(api.fetchRecommendation).mockResolvedValue(null);
});

afterEach(() => vi.restoreAllMocks());

describe("LogisticsTender", () => {
  it("показывает индикатор загрузки, пока грузятся тендеры", () => {
    // подвешенный промис — компонент остаётся в состоянии loading
    m(api.fetchRfqs).mockReturnValue(new Promise<Rfq[]>(() => {}));
    render(<LogisticsTender />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  });

  it("пустой список тендеров показывает EmptyState с кнопкой демо-тендера", async () => {
    m(api.fetchRfqs).mockResolvedValue([]);
    render(<LogisticsTender />);
    expect(await screen.findByText("Тендеров (RFQ) пока нет.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать демо-тендер" })).toBeInTheDocument();
  });

  it("рендерит карточку тендера: номер, груз, вес, маршрут и русский статус", async () => {
    render(<LogisticsTender />);
    expect(await screen.findByText("RFQ-001")).toBeInTheDocument();
    // "Сталь листовая · 500 кг · Минск → Брест" — вес через formatNumber
    expect(screen.getByText(/Сталь листовая · 500 кг · Минск → Брест/)).toBeInTheDocument();
    // rfqStatusLabel("collecting") → "Сбор ставок"
    expect(screen.getByText("Сбор ставок")).toBeInTheDocument();
    // деталь ещё не выбрана — подсказка
    expect(screen.getByText(/Выберите тендер слева/)).toBeInTheDocument();
  });

  it("клик по тендеру грузит приглашения/ставки и показывает лучшую цену + экономию", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    m(api.fetchInvites).mockResolvedValue(invites);
    render(<LogisticsTender />);

    fireEvent.click(await screen.findByText("RFQ-001"));

    await waitFor(() => expect(api.fetchRankedBids).toHaveBeenCalledWith(1));
    expect(api.fetchInvites).toHaveBeenCalledWith(1);
    expect(api.fetchRecommendation).toHaveBeenCalledWith(1);

    // ставки в таблице; "Альфа Транс" — и в строке таблицы, и в сводке «Дешевле всех»
    expect((await screen.findAllByText("Альфа Транс")).length).toBeGreaterThan(0);
    expect(screen.getByText("Бета Логистик")).toBeInTheDocument();
    // bestBid = самый дешёвый (800 BYN — в таблице и в сводке); экономия = 950-800 = 150 BYN
    expect(screen.getByText(/Дешевле всех:/)).toBeInTheDocument();
    expect(screen.getAllByText("800 BYN").length).toBeGreaterThan(0);
    expect(screen.getByText(/Экономия от конкуренции:/)).toBeInTheDocument();
    expect(screen.getByText("150 BYN")).toBeInTheDocument();
    // value_score 0.9 → 90 в колонке "Соотн."
    expect(screen.getByText("90")).toBeInTheDocument();
    // приглашения показаны в блоке рассылки
    expect(screen.getByText("Рассылка приглашений")).toBeInTheDocument();
  });

  it("выбранный тендер без ставок показывает подсказку «Ставок ещё нет»", async () => {
    m(api.fetchRankedBids).mockResolvedValue([]);
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    expect(await screen.findByText(/Ставок ещё нет/)).toBeInTheDocument();
  });

  // Каждая стратегия — отдельным рендером: после присуждения тендер переходит в
  // состояние «awarded» и кнопки стратегий исчезают, поэтому два клика в одном
  // рендере — гонка. Проверяем изолированно, свежий маунт на каждый кейс.
  const awarded = {
    rfq_id: 1,
    status: "awarded",
    carrier_code: "ALFA",
    carrier: "Альфа Транс",
    price: 800,
    shipment_id: 5,
    shipment_number: "SHP-5",
  };

  it("«По цене» присуждает по стратегии cheapest", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    m(api.awardRfq).mockResolvedValue(awarded);
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    await screen.findByText("Бета Логистик");

    fireEvent.click(screen.getByRole("button", { name: "По цене" }));
    await waitFor(() => expect(api.awardRfq).toHaveBeenCalledWith(1, undefined, "cheapest"));
  });

  it("«По соотношению» присуждает по стратегии best_value", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    m(api.awardRfq).mockResolvedValue(awarded);
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    await screen.findByText("Бета Логистик");

    fireEvent.click(screen.getByRole("button", { name: "По соотношению" }));
    await waitFor(() => expect(api.awardRfq).toHaveBeenCalledWith(1, undefined, "best_value"));
  });

  it("«Разослать» вызывает broadcastRfq и показывает счётчик уведомлённых", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    m(api.fetchInvites).mockResolvedValue(invites);
    m(api.broadcastRfq).mockResolvedValue({
      rfq_id: 1,
      status: "sent",
      invited: 2,
      notified: 1,
      carriers: ["ALFA", "BETA"],
    });
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    await screen.findByText("Бета Логистик");

    fireEvent.click(screen.getByRole("button", { name: "Разослать" }));

    await waitFor(() => expect(api.broadcastRfq).toHaveBeenCalledWith(1));
    // lastBroadcast → "уведомлено 1 из 2"
    expect(await screen.findByText(/уведомлено 1 из 2/)).toBeInTheDocument();
  });

  it("«Торг» шлёт контр-ставку negotiateBid с введённой ценой и комментарием", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    m(api.negotiateBid).mockResolvedValue(null);
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockReturnValueOnce("750") // новая цена
      .mockReturnValueOnce("успеть к пятнице"); // комментарий
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    await screen.findByText("Бета Логистик");

    // первая строка (ALFA) — жмём «Торг»
    fireEvent.click(screen.getAllByRole("button", { name: "Торг" })[0]);

    expect(promptSpy).toHaveBeenCalled();
    await waitFor(() =>
      expect(api.negotiateBid).toHaveBeenCalledWith(1, "ALFA", 750, "успеть к пятнице"),
    );
  });

  it("отмена диалога торга (prompt → null) не вызывает negotiateBid", async () => {
    m(api.fetchRankedBids).mockResolvedValue(bids);
    vi.spyOn(window, "prompt").mockReturnValue(null);
    render(<LogisticsTender />);
    fireEvent.click(await screen.findByText("RFQ-001"));
    await screen.findByText("Бета Логистик");

    fireEvent.click(screen.getAllByRole("button", { name: "Торг" })[0]);
    expect(api.negotiateBid).not.toHaveBeenCalled();
  });

  it("присуждённый тендер показывает победителя и цену на карточке списка", async () => {
    m(api.fetchRfqs).mockResolvedValue([
      { ...rfq, status: "awarded", awarded_carrier_code: "ALFA", awarded_price: 800 },
    ]);
    render(<LogisticsTender />);
    expect(await screen.findByText(/Победитель: ALFA · 800 BYN/)).toBeInTheDocument();
  });
});
