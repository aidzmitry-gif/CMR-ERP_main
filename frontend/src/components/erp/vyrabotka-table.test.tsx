import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Мокаем ТОЛЬКО сетевые функции домена; чистые хелперы (formatByn/formatNh/
// contributionShare/totalContribution) оставляем настоящими — их и проверяем через UI.
vi.mock("@/lib/production-vyrabotka", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/production-vyrabotka")>();
  return {
    ...actual,
    fetchPayroll: vi.fn(),
    fetchWorkers: vi.fn(),
    createWorker: vi.fn(),
  };
});

import { VyrabotkaTable } from "@/components/erp/vyrabotka-table";
import * as vyr from "@/lib/production-vyrabotka";
import type { Payroll, Worker } from "@/lib/production-vyrabotka";

const fn = (m: unknown) => m as ReturnType<typeof vi.fn>;

// Двое сборщиков: лидер (вклад 250 из 400 = 62.5%) и второй (150/400 = 37.5%).
// Суммы < 1000 — без разделителя тысяч, чтобы ассерты по BYN были стабильны.
const payroll: Payroll = {
  rows: [
    { id: 1, name: "Иванов", nh_output: 40, base: 500, premium: 250, total: 750, contribution: 250 },
    { id: 2, name: "Петров", nh_output: 24, base: 300, premium: 150, total: 450, contribution: 150 },
  ],
  total_nh: 64,
  total_base: 800,
  total_premium: 400,
  total_payroll: 1200,
};

const emptyPayroll: Payroll = {
  rows: [],
  total_nh: 0,
  total_base: 0,
  total_premium: 0,
  total_payroll: 0,
};

const workers: Worker[] = [
  { id: 1, name: "Иванов", salary: 1100, days_worked: 22, nh_output: 40 },
  { id: 2, name: "Петров", salary: 900, days_worked: 20, nh_output: 24 },
];

beforeEach(() => {
  vi.clearAllMocks();
  // Компонент на маунте всегда рефетчит — без этих дефолтов .then упадёт на undefined.
  fn(vyr.fetchPayroll).mockResolvedValue(emptyPayroll);
  fn(vyr.fetchWorkers).mockResolvedValue([]);
  fn(vyr.createWorker).mockResolvedValue(workers[0]);
});

describe("VyrabotkaTable", () => {
  it("рендерит строки табеля и долю вклада (contributionShare) из данных", async () => {
    fn(vyr.fetchPayroll).mockResolvedValue(payroll);
    fn(vyr.fetchWorkers).mockResolvedValue(workers);
    render(<VyrabotkaTable initial={payroll} />);

    expect(await screen.findByText("Иванов")).toBeInTheDocument();
    expect(screen.getByText("Петров")).toBeInTheDocument();
    // Итого ЗП по строкам — настоящий formatByn, суммы без разделителя тысяч.
    expect(screen.getByText("750 BYN")).toBeInTheDocument();
    expect(screen.getByText("450 BYN")).toBeInTheDocument();
    // Доли вклада: 250/400 и 150/400 → сломай contributionShare и эти числа поедут.
    expect(screen.getByText("62.5%")).toBeInTheDocument();
    expect(screen.getByText("37.5%")).toBeInTheDocument();
  });

  it("показывает пустое состояние, когда табель пуст", async () => {
    render(<VyrabotkaTable initial={emptyPayroll} />);
    expect(await screen.findByText("Табель пуст — добавьте сборщика")).toBeInTheDocument();
    // Кубок лидера не рисуется на пустом табеле.
    expect(document.querySelector("svg.lucide-trophy")).toBeNull();
  });

  it("кубок лидера — только у первой (топовой по вкладу) строки", async () => {
    fn(vyr.fetchPayroll).mockResolvedValue(payroll);
    render(<VyrabotkaTable initial={payroll} />);

    await screen.findByText("Иванов");
    const trophies = document.querySelectorAll("svg.lucide-trophy");
    expect(trophies).toHaveLength(1);
    // кубок именно в строке лидера (Иванов), не у Петрова
    const leaderRow = screen.getByText("Иванов").closest("tr") as HTMLElement;
    expect(within(leaderRow).getByText("Иванов")).toBeInTheDocument();
    expect(leaderRow.querySelector("svg.lucide-trophy")).not.toBeNull();
    const secondRow = screen.getByText("Петров").closest("tr") as HTMLElement;
    expect(secondRow.querySelector("svg.lucide-trophy")).toBeNull();
  });

  it("пустое имя — валидация: createWorker не зовётся, поле подсвечивается", async () => {
    render(<VyrabotkaTable initial={emptyPayroll} />);
    const nameInput = screen.getByPlaceholderText("Имя сборщика");
    expect(nameInput.className).not.toMatch(/border-amber-500/);

    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    expect(vyr.createWorker).not.toHaveBeenCalled();
    expect(nameInput.className).toMatch(/border-amber-500/);
  });

  it("добавление сборщика парсит поля (запятая→точка) и зовёт createWorker", async () => {
    render(<VyrabotkaTable initial={emptyPayroll} />);

    fireEvent.change(screen.getByPlaceholderText("Имя сборщика"), { target: { value: "  Сидоров  " } });
    fireEvent.change(screen.getByPlaceholderText("Оклад BYN"), { target: { value: "1200,5" } });
    fireEvent.change(screen.getByPlaceholderText("Дни"), { target: { value: "20" } });
    fireEvent.change(screen.getByPlaceholderText("Н.ч"), { target: { value: "40,5" } });

    fireEvent.click(screen.getByRole("button", { name: /Добавить/ }));

    await waitFor(() =>
      expect(vyr.createWorker).toHaveBeenCalledWith({
        name: "Сидоров", // trim
        salary: 1200.5, // "1200,5" → 1200.5
        days_worked: 20,
        nh_output: 40.5, // "40,5" → 40.5
      }),
    );
    // после успеха форма очищается и идёт рефетч
    await waitFor(() =>
      expect((screen.getByPlaceholderText("Имя сборщика") as HTMLInputElement).value).toBe(""),
    );
    // fetchPayroll вызван дважды: маунт + refresh после добавления
    expect(fn(vyr.fetchPayroll).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("после маунта подтягивает число записей в табеле из fetchWorkers", async () => {
    fn(vyr.fetchWorkers).mockResolvedValue(workers);
    render(<VyrabotkaTable initial={emptyPayroll} />);
    expect(await screen.findByText(/Записей в табеле: 2/)).toBeInTheDocument();
  });
});
