import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type Alerts,
  acceptReceipt,
  alertsEmitMessage,
  canEmitAlerts,
  createCyclePlan,
  dueState,
  emitAlerts,
  fetchAlertsServer,
  fetchCyclePlans,
  fetchCyclePlansServer,
  fetchDashboardServer,
  fetchReceipt,
  fetchReceiptServer,
  fetchReceiptsServer,
  fetchReconServer,
  fetchTasks,
  fetchTasksServer,
  fetchThresholdsServer,
  patchTask,
  qcReceipt,
  receiptStatusLabel,
  runCyclePlan,
  severityLabel,
  taskKindLabel,
  taskStatusLabel,
} from "@/lib/wms-warehouse";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("severityLabel", () => {
  it("переводит severity", () => {
    expect(severityLabel("out_of_stock")).toBe("Нет в наличии");
    expect(severityLabel("below_min")).toBe("Ниже минимума");
  });
});

describe("task labels", () => {
  it("kind/status", () => {
    expect(taskKindLabel("putaway")).toBe("Размещение");
    expect(taskKindLabel("pick")).toBe("Подбор");
    expect(taskStatusLabel("in_progress")).toBe("В работе");
    expect(taskStatusLabel("done")).toBe("Выполнена");
  });
});

describe("receiptStatusLabel", () => {
  it("статусы приёмки", () => {
    expect(receiptStatusLabel("pending_qc")).toBe("Ожидает QC");
    expect(receiptStatusLabel("accepted")).toBe("Принято");
  });
});

describe("dueState", () => {
  const today = "2026-06-28";
  it("просрочено / сегодня / предстоит / нет", () => {
    expect(dueState("2026-06-01", today)).toBe("overdue");
    expect(dueState(today, today)).toBe("today");
    expect(dueState("2026-07-10", today)).toBe("upcoming");
    expect(dueState(null, today)).toBe("none");
  });
});

describe("alertsEmitMessage", () => {
  it("русский плюрал позиции", () => {
    expect(alertsEmitMessage(1)).toBe("Сигнал отправлен в закупки, 1 позиция");
    expect(alertsEmitMessage(3)).toBe("Сигнал отправлен в закупки, 3 позиции");
    expect(alertsEmitMessage(5)).toBe("Сигнал отправлен в закупки, 5 позиций");
    expect(alertsEmitMessage(11)).toBe("Сигнал отправлен в закупки, 11 позиций");
    expect(alertsEmitMessage(21)).toBe("Сигнал отправлен в закупки, 21 позиция");
  });
});

describe("canEmitAlerts", () => {
  const row = {
    sku_code: "AKB-60", title: "АКБ", warehouse: "Минск",
    free_qty: 3, min_qty: 10, deficit: 7, reorder_qty: 20, severity: "below_min",
  };
  it("кнопка активна только при шлюзе и нарушенных порогах", () => {
    expect(canEmitAlerts({ rows: [row], gateway: true } as Alerts)).toBe(true);
    expect(canEmitAlerts({ rows: [], gateway: true } as Alerts)).toBe(false); // пусто → disabled
    expect(canEmitAlerts({ rows: [row], gateway: false } as Alerts)).toBe(false); // нет 1С
  });
});

describe("SSR fetch-обёртки (ssr helper)", () => {
  it("fetchDashboardServer: URL/заголовки-роли, маппинг ответа", async () => {
    const data = {
      receipts_pending_qc: 3, tasks_putaway_open: 1, tasks_pick_open: 2, alerts_count: 4,
      alerts_deficit_value: 500, inventory_value: 10000, inventories_open: 1,
      recon_max_diff_value: 20, recon_total_diff_value: 40, movements_today_in: 5,
      movements_today_out: 6, gateway: true,
    };
    const fn = stubFetch(data);
    const res = await fetchDashboardServer("sales");
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/dashboard",
      expect.objectContaining({ cache: "no-store", headers: { "X-User-Roles": "sales" } }),
    );
    expect(res).toEqual(data);
  });

  it("fetchDashboardServer: без ролей — headers undefined; !ok — дефолт с нулями", async () => {
    const fn = stubFetch({}, false);
    const res = await fetchDashboardServer();
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/dashboard",
      expect.objectContaining({ headers: undefined }),
    );
    expect(res).toEqual({
      receipts_pending_qc: 0, tasks_putaway_open: 0, tasks_pick_open: 0, alerts_count: 0,
      alerts_deficit_value: 0, inventory_value: 0,
      inventories_open: 0, recon_max_diff_value: 0, recon_total_diff_value: 0,
      movements_today_in: 0, movements_today_out: 0, gateway: false,
    });
  });

  it("fetchDashboardServer: сетевая ошибка — дефолт с gateway:false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    const res = await fetchDashboardServer();
    expect(res.gateway).toBe(false);
    expect(res.inventory_value).toBe(0);
  });

  it("fetchReceiptsServer / fetchTasksServer / fetchCyclePlansServer / fetchThresholdsServer — пустой fallback при ошибке", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await fetchReceiptsServer()).toEqual([]);
    expect(await fetchTasksServer()).toEqual([]);
    expect(await fetchCyclePlansServer()).toEqual([]);
    expect(await fetchThresholdsServer()).toEqual([]);
  });

  it("fetchReceiptServer: URL с id, null при !ok", async () => {
    const fn = stubFetch({ id: 9, number: "R-9", lines: [] });
    const res = await fetchReceiptServer("9", "warehouse");
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/receipts/9",
      expect.objectContaining({ headers: { "X-User-Roles": "warehouse" } }),
    );
    expect(res?.number).toBe("R-9");

    stubFetch({}, false);
    expect(await fetchReceiptServer("9")).toBeNull();
  });

  it("fetchReconServer: маппит строки и total_abs_diff_value; дефолт при ошибке", async () => {
    const data = {
      rows: [{ sku_code: "A", title: "t", warehouse: "w", wms_qty: 1, onec_qty: 2, diff: -1, diff_value: -50 }],
      gateway: true, total_abs_diff_value: 50,
    };
    stubFetch(data);
    expect(await fetchReconServer()).toEqual(data);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await fetchReconServer()).toEqual({ rows: [], gateway: false, total_abs_diff_value: 0 });
  });

  it("fetchAlertsServer: маппит строки; дефолт при ошибке", async () => {
    const data = {
      rows: [{ sku_code: "A", title: "t", warehouse: "w", free_qty: 1, min_qty: 5, deficit: 4, reorder_qty: 10, severity: "below_min" }],
      gateway: true,
    };
    stubFetch(data);
    expect(await fetchAlertsServer()).toEqual(data);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await fetchAlertsServer()).toEqual({ rows: [], gateway: false });
  });
});

describe("Client fetch-обёртки (api/post helpers)", () => {
  it("fetchReceipt: правильный URL через /api, маппит; null при !ok/ошибке", async () => {
    const fn = stubFetch({ id: 5, number: "R-5", lines: [{ id: 1, sku_code: "A" }] });
    const res = await fetchReceipt(5);
    expect(fn).toHaveBeenCalledWith("/api/wms/receipts/5", expect.objectContaining({ cache: "no-store" }));
    expect(res?.number).toBe("R-5");

    stubFetch({}, false);
    expect(await fetchReceipt(5)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchReceipt(5)).toBeNull();
  });

  it("fetchTasks / fetchCyclePlans: маппинг при успехе, пустой список при ошибке", async () => {
    stubFetch([{ id: 1, kind: "pick" }]);
    expect((await fetchTasks())[0].kind).toBe("pick");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchTasks()).toEqual([]);

    stubFetch([{ id: 2, warehouse: "w1" }]);
    expect((await fetchCyclePlans())[0].warehouse).toBe("w1");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchCyclePlans()).toEqual([]);
  });

  it("qcReceipt: POST с decisions/decided_by в теле; decidedBy по умолчанию ''", async () => {
    const fn = stubFetch({}, true);
    const ok = await qcReceipt(3, [{ line_id: 1, accepted_qty: 2 }], "Иванов");
    expect(ok).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/wms/receipts/3/qc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decisions: [{ line_id: 1, accepted_qty: 2 }], decided_by: "Иванов" }),
    });

    const fn2 = stubFetch({}, true);
    await qcReceipt(3, []);
    expect(fn2).toHaveBeenCalledWith("/api/wms/receipts/3/qc", expect.objectContaining({
      body: JSON.stringify({ decisions: [], decided_by: "" }),
    }));

    stubFetch({}, false);
    expect(await qcReceipt(3, [])).toBe(false);
  });

  it("acceptReceipt: POST без тела на верный URL; false при !ok/ошибке", async () => {
    const fn = stubFetch({}, true);
    expect(await acceptReceipt(3)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/wms/receipts/3/accept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: undefined,
    });

    stubFetch({}, false);
    expect(await acceptReceipt(3)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await acceptReceipt(3)).toBe(false);
  });

  it("patchTask: PATCH с телом на верный URL; false при !ok/ошибке", async () => {
    const fn = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fn);
    const ok = await patchTask(7, { status: "done" });
    expect(ok).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/wms/tasks/7", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "done" }),
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    expect(await patchTask(7, { status: "done" })).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await patchTask(7, { status: "done" })).toBe(false);
  });

  it("createCyclePlan: POST тела на верный URL", async () => {
    const fn = stubFetch({}, true);
    const body = { warehouse: "w1", zone: null, cadence_days: 30 };
    expect(await createCyclePlan(body)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/wms/cycle-plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    stubFetch({}, false);
    expect(await createCyclePlan(body)).toBe(false);
  });

  it("emitAlerts: возвращает { emitted } при успехе, null при !ok/ошибке", async () => {
    const fn = stubFetch({ emitted: 4 });
    const res = await emitAlerts();
    expect(fn).toHaveBeenCalledWith("/api/wms/alerts/emit", { method: "POST" });
    expect(res).toEqual({ emitted: 4 });

    stubFetch({}, false);
    expect(await emitAlerts()).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("503")));
    expect(await emitAlerts()).toBeNull();
  });

  it("runCyclePlan: возвращает { id } на верном URL; null при !ok/ошибке", async () => {
    const fn = stubFetch({ id: 42 });
    const res = await runCyclePlan(9);
    expect(fn).toHaveBeenCalledWith("/api/wms/cycle-plans/9/run", { method: "POST" });
    expect(res).toEqual({ id: 42 });

    stubFetch({}, false);
    expect(await runCyclePlan(9)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await runCyclePlan(9)).toBeNull();
  });
});
