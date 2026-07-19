import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО data-fetch слой логистики (fetch-обёртки). Доменная логика
// (auditSummary/auditVariance) и форматирование денег (formatByn) — НЕ мокаются:
// компонент должен считать отклонение и деньги по-настоящему.
vi.mock("@/lib/logistics-api", () => ({
  fetchAudit: vi.fn(),
  seedAudit: vi.fn(),
  createAuditEntry: vi.fn(),
}));

import { LogisticsAudit } from "@/components/erp/logistics-audit";
import * as api from "@/lib/logistics-api";
import type { AuditEntry, AuditReport } from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const entry = (over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: 1,
  shipment_code: "ЛОГ-2026-0001",
  carrier_code: "dpd",
  invoice_amount: 42,
  expected_amount: 30,
  variance: 12,
  reason: "доплата за вес",
  status: "open",
  ...over,
});

const report = (over: Partial<AuditReport> = {}): AuditReport => ({
  period: "2026-06",
  checked: 2,
  discrepancies: 1,
  to_recover: 12,
  items: [
    entry(),
    entry({ id: 2, shipment_code: "ЛОГ-2026-0002", carrier_code: "autolight", invoice_amount: 18, expected_amount: 20, variance: -2, reason: "", status: "ok" }),
  ],
  ...over,
});

const mocked = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  // Дефолт: непустой отчёт, чтобы компонент вышел из loading.
  mocked(api.fetchAudit).mockResolvedValue(report());
  mocked(api.seedAudit).mockResolvedValue([]);
  mocked(api.createAuditEntry).mockResolvedValue(null);
});

describe("LogisticsAudit", () => {
  it("показывает индикатор загрузки до ответа, затем KPI и таблицу", async () => {
    // fetchAudit ещё не резолвнут на первом кадре → виден «Загрузка…»
    render(<LogisticsAudit />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();

    // после ответа — KPI-плитки и содержимое таблицы
    expect(await screen.findByText("Проверено счетов")).toBeInTheDocument();
    expect(screen.getByText("Расхождений")).toBeInTheDocument();
    expect(screen.getByText("К возврату")).toBeInTheDocument();
    expect(screen.getByText("ЛОГ-2026-0001")).toBeInTheDocument();
    expect(screen.queryByText("Загрузка…")).not.toBeInTheDocument();
  });

  it("KPI «Проверено» берёт число из свода backend, а не из длины списка", async () => {
    // checked=5 при 2 позициях — компонент должен доверять своду сервера (строка report?.checked ??)
    mocked(api.fetchAudit).mockResolvedValue(report({ checked: 5, discrepancies: 3, to_recover: 40 }));
    render(<LogisticsAudit />);

    const tile = (await screen.findByText("Проверено счетов")).closest("div")?.parentElement;
    expect(tile).toHaveTextContent("5");
    // «К возврату» форматируется в BYN настоящей formatByn
    expect(screen.getByText(formatByn(40))).toBeInTheDocument();
  });

  it("считает и подписывает отклонение по знаку (переплата со знаком +, экономия — как есть)", async () => {
    render(<LogisticsAudit />);
    await screen.findByText("ЛОГ-2026-0001");

    // invoice 42 − expected 30 = +12 (переплата) → префикс «+»
    expect(screen.getByText("+" + formatByn(12))).toBeInTheDocument();
    // invoice 18 − expected 20 = −2 (экономия) → без ручного «+», знак от formatByn
    expect(screen.getByText(formatByn(-2))).toBeInTheDocument();
    // суммы счетов форматируются в BYN
    expect(screen.getByText(formatByn(42))).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
  });

  it("при пустом периоде показывает подсказку вместо таблицы", async () => {
    mocked(api.fetchAudit).mockResolvedValue(report({ items: [], checked: 0, discrepancies: 0, to_recover: 0 }));
    render(<LogisticsAudit />);

    expect(await screen.findByText(/Счетов за 2026-06 ещё нет/)).toBeInTheDocument();
    expect(screen.queryByText("ЛОГ-2026-0001")).not.toBeInTheDocument();
  });

  it("валидация: без обязательных полей — ошибка, счёт в backend не уходит", async () => {
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");

    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(
      await screen.findByText(/Заполните № отгрузки, код перевозчика и сумму счёта/),
    ).toBeInTheDocument();
    expect(api.createAuditEntry).not.toHaveBeenCalled();
  });

  it("валидация: неположительная сумма счёта — ошибка, счёт не уходит", async () => {
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");

    fireEvent.change(screen.getByPlaceholderText("напр. ЛОГ-2026-0099"), { target: { value: "ЛОГ-9" } });
    fireEvent.change(screen.getByPlaceholderText("dpd / autolight / …"), { target: { value: "dpd" } });
    fireEvent.change(screen.getByPlaceholderText("30.00"), { target: { value: "-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(
      await screen.findByText(/Сумма счёта должна быть положительным числом/),
    ).toBeInTheDocument();
    expect(api.createAuditEntry).not.toHaveBeenCalled();
  });

  it("успешная регистрация: баннер с отклонением + пометкой финансов, перезагрузка отчёта, очистка формы", async () => {
    mocked(api.createAuditEntry).mockResolvedValue(
      entry({ id: 10, shipment_code: "ЛОГ-2026-0099", invoice_amount: 35, expected_amount: 30, variance: 5 }),
    );
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");
    expect(api.fetchAudit).toHaveBeenCalledTimes(1); // маунт

    fireEvent.change(screen.getByPlaceholderText("напр. ЛОГ-2026-0099"), { target: { value: "ЛОГ-2026-0099" } });
    fireEvent.change(screen.getByPlaceholderText("dpd / autolight / …"), { target: { value: "dpd" } });
    fireEvent.change(screen.getByPlaceholderText("30.00"), { target: { value: "35" } });
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    await waitFor(() =>
      expect(api.createAuditEntry).toHaveBeenCalledWith(
        expect.objectContaining({ shipment_code: "ЛОГ-2026-0099", carrier_code: "dpd", invoice_amount: 35 }),
      ),
    );
    // баннер успеха (текст-нода div-а без учёта вложенного span со суммой)
    expect(await screen.findByText(/зарегистрирован, отклонение/)).toBeInTheDocument();
    expect(screen.getByText("+" + formatByn(5))).toBeInTheDocument();
    expect(screen.getByText(/в финансы ушло событие к возврату/)).toBeInTheDocument();
    // отчёт перезагружен (второй вызов fetchAudit)
    await waitFor(() => expect(api.fetchAudit).toHaveBeenCalledTimes(2));
    // форма очищена
    expect(screen.getByPlaceholderText("напр. ЛОГ-2026-0099")).toHaveValue("");
  });

  it("сбой регистрации (backend вернул null) показывает ошибку, а не баннер успеха", async () => {
    mocked(api.createAuditEntry).mockResolvedValue(null);
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");

    fireEvent.change(screen.getByPlaceholderText("напр. ЛОГ-2026-0099"), { target: { value: "ЛОГ-X" } });
    fireEvent.change(screen.getByPlaceholderText("dpd / autolight / …"), { target: { value: "dpd" } });
    fireEvent.change(screen.getByPlaceholderText("30.00"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    expect(await screen.findByText(/Не удалось зарегистрировать счёт/)).toBeInTheDocument();
    expect(screen.queryByText(/зарегистрирован, отклонение/)).not.toBeInTheDocument();
  });

  it("кнопка «Обновить демо» засевает данные и перечитывает отчёт", async () => {
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");
    expect(api.fetchAudit).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Обновить демо" }));

    await waitFor(() => expect(api.seedAudit).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.fetchAudit).toHaveBeenCalledTimes(2));
  });

  it("смена периода перечитывает отчёт за новый период и обновляет подсказку", async () => {
    render(<LogisticsAudit />);
    await screen.findByText("Проверено счетов");

    // следующий ответ — пустой отчёт за новый период
    mocked(api.fetchAudit).mockResolvedValue(report({ period: "2026-07", items: [], checked: 0, discrepancies: 0, to_recover: 0 }));
    fireEvent.change(screen.getByPlaceholderText("ГГГГ-ММ"), { target: { value: "2026-07" } });

    await waitFor(() => expect(api.fetchAudit).toHaveBeenCalledWith("2026-07"));
    expect(await screen.findByText(/Счетов за 2026-07 ещё нет/)).toBeInTheDocument();
  });
});
