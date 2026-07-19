import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевые функции домена ОТК; чистые хелперы (decisionLabel,
// formatPassRate, REWORK_REASONS) оставляем реальными — компонент показывает
// их вывод, и тесты должны проверять именно его.
vi.mock("@/lib/production-otk", async () => {
  const actual = await vi.importActual<typeof import("@/lib/production-otk")>(
    "@/lib/production-otk",
  );
  return {
    ...actual,
    fetchStats: vi.fn(),
    fetchDecisions: vi.fn(),
    createDecision: vi.fn(),
  };
});

import { OtkPanel } from "@/components/erp/otk-panel";
import * as otk from "@/lib/production-otk";
import type { QcRecord, QcStats } from "@/lib/production-otk";

const fetchStats = otk.fetchStats as ReturnType<typeof vi.fn>;
const fetchDecisions = otk.fetchDecisions as ReturnType<typeof vi.fn>;
const createDecision = otk.createDecision as ReturnType<typeof vi.fn>;

const STATS: QcStats = { accepted: 12, rework: 3, scrap: 1, total: 16, pass_rate: 96 };

const RECORD: QcRecord = {
  id: 1,
  order_code: "№12",
  product: "АКБ 48В 100Ач",
  decision: "scrap",
  reason: "прожог сварного шва",
  inspector: "Пётр",
};

beforeEach(() => {
  vi.clearAllMocks();
  // По умолчанию маунт-эффект возвращает те же initial-данные (state не «прыгает»).
  fetchStats.mockResolvedValue(STATS);
  fetchDecisions.mockResolvedValue([RECORD]);
});

describe("OtkPanel", () => {
  it("показывает KPI (pass-rate, принято/доработка/брак) из initialStats", async () => {
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);
    // pass_rate 96 → «96%» через formatPassRate (реальный хелпер, не мок)
    expect(screen.getByText("96%")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument(); // принято
    expect(screen.getByText("3")).toBeInTheDocument(); // доработка
    expect(screen.getAllByText("1").length).toBeGreaterThan(0); // брак
    await waitFor(() => expect(fetchStats).toHaveBeenCalled());
  });

  it("рендерит строку журнала с изделием, причиной и русской подписью решения", async () => {
    render(<OtkPanel initialStats={STATS} initialJournal={[RECORD]} />);
    const row = screen.getByText("АКБ 48В 100Ач").closest("tr") as HTMLElement;
    expect(row).not.toBeNull();
    expect(within(row).getByText("прожог сварного шва")).toBeInTheDocument();
    expect(within(row).getByText("Пётр")).toBeInTheDocument();
    // decisionLabel("scrap") → «Брак» (реальный хелпер) — внутри строки, не в KPI
    expect(within(row).getByText("Брак")).toBeInTheDocument();
    await waitFor(() => expect(fetchDecisions).toHaveBeenCalled());
  });

  it("пустой журнал показывает заглушку «Решений пока нет»", async () => {
    fetchDecisions.mockResolvedValue([]); // и маунт-фетч пуст
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);
    expect(screen.getByText("Решений пока нет")).toBeInTheDocument();
    await waitFor(() => expect(fetchDecisions).toHaveBeenCalled());
  });

  it("маунт-эффект дозагружает решения и добавляет строку в журнал", async () => {
    // initial пуст, но fetchDecisions на маунте вернёт запись → она появится
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);
    expect(await screen.findByText("АКБ 48В 100Ач")).toBeInTheDocument();
    expect(screen.queryByText("Решений пока нет")).not.toBeInTheDocument();
  });

  it("«На доработку» шлёт createDecision с обрезанными полями и причиной", async () => {
    createDecision.mockResolvedValue(RECORD);
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);

    fireEvent.change(screen.getByPlaceholderText("№ наряда"), { target: { value: "  42  " } });
    fireEvent.change(screen.getByPlaceholderText("Изделие"), { target: { value: "  АКБ 190  " } });
    fireEvent.change(screen.getByPlaceholderText(/Причина/), { target: { value: "  непропай  " } });

    fireEvent.click(screen.getByRole("button", { name: /На доработку/ }));

    await waitFor(() => expect(createDecision).toHaveBeenCalledTimes(1));
    expect(createDecision).toHaveBeenCalledWith({
      decision: "rework",
      order_code: "42",
      product: "АКБ 190",
      inspector: "Никита", // дефолтный контролёр
      reason: "непропай",
    });
  });

  it("«Принять» обнуляет причину (для accept причина не отправляется)", async () => {
    createDecision.mockResolvedValue(RECORD);
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);

    // причину ввели, но для accept она должна уйти пустой (ветка decision === "accept")
    fireEvent.change(screen.getByPlaceholderText(/Причина/), { target: { value: "лишнее" } });
    fireEvent.click(screen.getByRole("button", { name: /Принять/ }));

    await waitFor(() => expect(createDecision).toHaveBeenCalled());
    expect(createDecision.mock.calls[0][0]).toMatchObject({ decision: "accept", reason: "" });
  });

  it("после решения обновляет журнал и KPI из refresh-фетча", async () => {
    const NEW: QcRecord = { ...RECORD, id: 2, product: "Свежий блок", decision: "accept", reason: "" };
    // маунт: пусто; refresh после решения: новая запись + новые stats
    fetchDecisions.mockResolvedValueOnce([]).mockResolvedValue([NEW]);
    fetchStats.mockResolvedValueOnce(STATS).mockResolvedValue({ ...STATS, accepted: 13, pass_rate: 95.5 });
    createDecision.mockResolvedValue(NEW);

    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);
    expect(await screen.findByText("Решений пока нет")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Принять/ }));

    // журнал перезагрузился новой записью
    expect(await screen.findByText("Свежий блок")).toBeInTheDocument();
    // pass_rate 95.5 → «95,5%» (запятая) из refresh-статистики
    expect(screen.getByText("95,5%")).toBeInTheDocument();
    expect(fetchDecisions).toHaveBeenCalledTimes(2); // маунт + refresh
  });

  it("во время отправки кнопки решений заблокированы (busy)", async () => {
    let release!: (v: QcRecord) => void;
    createDecision.mockImplementation(() => new Promise((r) => (release = r)));
    render(<OtkPanel initialStats={STATS} initialJournal={[]} />);

    const accept = screen.getByRole("button", { name: /Принять/ });
    const rework = screen.getByRole("button", { name: /На доработку/ });
    fireEvent.click(accept);

    await waitFor(() => expect(accept).toBeDisabled());
    expect(rework).toBeDisabled();

    release(RECORD); // разблокировали → busy снят
    await waitFor(() => expect(accept).not.toBeDisabled());
  });
});
