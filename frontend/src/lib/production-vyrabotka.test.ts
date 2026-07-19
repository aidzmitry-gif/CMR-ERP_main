import { afterEach, describe, expect, it, vi } from "vitest";

import {
  contributionShare,
  createWorker,
  fetchPayroll,
  fetchPayrollServer,
  fetchWorkers,
  formatByn,
  formatNh,
  type Payroll,
  type PayrollRow,
  totalContribution,
  updateWorker,
} from "@/lib/production-vyrabotka";

function jsonResponse(data: unknown, ok = true): Response {
  return { ok, json: async () => data } as Response;
}

const EMPTY_PAYROLL: Payroll = {
  rows: [],
  total_nh: 0,
  total_base: 0,
  total_premium: 0,
  total_payroll: 0,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function row(over: Partial<PayrollRow>): PayrollRow {
  return {
    id: 1,
    name: "Сборщик",
    nh_output: 0,
    base: 0,
    premium: 0,
    total: 0,
    contribution: 0,
    ...over,
  };
}

// ru-RU группирует тысячи неразрывным пробелом (U+00A0); \s в JS-regex его матчит.
const stripWs = (s: string) => s.replace(/\s/g, "");

describe("production-vyrabotka", () => {
  it("formatByn: русский формат с суффиксом BYN", () => {
    expect(formatByn(910)).toBe("910 BYN");
    expect(formatByn(910.5)).toBe("910,5 BYN");
    expect(formatByn(0)).toBe("0 BYN");
    expect(stripWs(formatByn(1067.5))).toBe("1067,5BYN");
  });

  it("formatNh реэкспортирован из norms", () => {
    expect(formatNh(7.5)).toBe("7,5");
    expect(formatNh(0)).toBe("—");
  });

  it("totalContribution: сумма вкладов", () => {
    const rows = [row({ contribution: 1000 }), row({ contribution: 472.5 })];
    expect(totalContribution(rows)).toBe(1472.5);
  });

  it("contributionShare: доля вклада в процентах", () => {
    expect(contributionShare(row({ contribution: 750 }), 1000)).toBe(75);
    expect(contributionShare(row({ contribution: 250 }), 1000)).toBe(25);
  });

  it("contributionShare: ноль при пустом итоге", () => {
    expect(contributionShare(row({ contribution: 100 }), 0)).toBe(0);
  });
});

describe("fetchPayrollServer", () => {
  it("зовёт BASE/production/payroll с no-store и без ролей, возвращает данные", async () => {
    const payload: Payroll = {
      rows: [
        {
          id: 1,
          name: "Иванов",
          nh_output: 10,
          base: 500,
          premium: 62.5,
          total: 562.5,
          contribution: 62.5,
        },
      ],
      total_nh: 10,
      total_base: 500,
      total_premium: 62.5,
      total_payroll: 562.5,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchPayrollServer();

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/payroll", {
      cache: "no-store",
      headers: undefined,
    });
    expect(result).toEqual(payload);
  });

  it("передаёт заголовок X-User-Roles, если роли переданы", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(EMPTY_PAYROLL));
    vi.stubGlobal("fetch", fetchMock);

    await fetchPayrollServer("director,rop");

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/payroll", {
      cache: "no-store",
      headers: { "X-User-Roles": "director,rop" },
    });
  });

  it("возвращает EMPTY_PAYROLL при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    const result = await fetchPayrollServer();
    expect(result).toEqual(EMPTY_PAYROLL);
  });

  it("возвращает EMPTY_PAYROLL при исключении fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const result = await fetchPayrollServer();
    expect(result).toEqual(EMPTY_PAYROLL);
  });
});

describe("fetchPayroll", () => {
  it("зовёт /api/production/payroll и возвращает данные", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(EMPTY_PAYROLL));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchPayroll();

    expect(fetchMock).toHaveBeenCalledWith("/api/production/payroll", { cache: "no-store" });
    expect(result).toEqual(EMPTY_PAYROLL);
  });

  it("возвращает EMPTY_PAYROLL при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await fetchPayroll()).toEqual(EMPTY_PAYROLL);
  });

  it("возвращает EMPTY_PAYROLL при исключении", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchPayroll()).toEqual(EMPTY_PAYROLL);
  });
});

describe("fetchWorkers", () => {
  it("зовёт /api/production/workers, возвращает список", async () => {
    const workers = [{ id: 1, name: "Иванов", salary: 1000, days_worked: 20, nh_output: 5 }];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(workers));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWorkers();

    expect(fetchMock).toHaveBeenCalledWith("/api/production/workers", { cache: "no-store" });
    expect(result).toEqual(workers);
  });

  it("возвращает [] при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await fetchWorkers()).toEqual([]);
  });

  it("возвращает [] при исключении", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchWorkers()).toEqual([]);
  });
});

describe("createWorker", () => {
  it("POST с JSON-телом на /api/production/workers, возвращает созданного", async () => {
    const input = { name: "Петров", salary: 900, days_worked: 22, nh_output: 3 };
    const created = { id: 5, ...input };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(created));
    vi.stubGlobal("fetch", fetchMock);

    const result = await createWorker(input);

    expect(fetchMock).toHaveBeenCalledWith("/api/production/workers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(created);
  });

  it("возвращает null при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await createWorker({ name: "X" })).toBeNull();
  });

  it("возвращает null при исключении", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await createWorker({ name: "X" })).toBeNull();
  });
});

describe("updateWorker", () => {
  it("PATCH с JSON-телом на /api/production/workers/{id}", async () => {
    const patch = { salary: 1200 };
    const updated = { id: 7, name: "Сидоров", salary: 1200, days_worked: 20, nh_output: 4 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated));
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateWorker(7, patch);

    expect(fetchMock).toHaveBeenCalledWith("/api/production/workers/7", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    expect(result).toEqual(updated);
  });

  it("возвращает null при ok:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));
    expect(await updateWorker(1, { salary: 1 })).toBeNull();
  });

  it("возвращает null при исключении", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await updateWorker(1, { salary: 1 })).toBeNull();
  });
});
