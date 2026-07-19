import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/wms-warehouse", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/wms-warehouse")>();
  return {
    ...actual,
    emitAlerts: vi.fn(),
  };
});

import { WmsAlerts } from "@/components/erp/wms-alerts";
import * as wh from "@/lib/wms-warehouse";
import type { Alerts, AlertRow } from "@/lib/wms-warehouse";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

function row(over: Partial<AlertRow> = {}): AlertRow {
  return {
    sku_code: "SKU-1",
    title: "Аккумулятор 18650",
    warehouse: "Главный",
    free_qty: 3,
    min_qty: 10,
    deficit: 7,
    reorder_qty: 20,
    severity: "below_min",
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WmsAlerts", () => {
  it("без шлюза 1С показывает баннер и не рендерит таблицу", () => {
    const data: Alerts = { rows: [], gateway: false };
    render(<WmsAlerts initial={data} />);
    expect(screen.getByText("Источник 1С не подключён — дефицит не рассчитан.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("с шлюзом, но без строк — показывает заглушку «Дефицита нет»", () => {
    const data: Alerts = { rows: [], gateway: true };
    render(<WmsAlerts initial={data} />);
    expect(screen.getByText("Дефицита нет — все остатки выше порогов")).toBeInTheDocument();
  });

  it("рендерит строки дефицита с реальными числами и лейблом статуса", () => {
    const data: Alerts = {
      gateway: true,
      rows: [row({ sku_code: "SKU-1", severity: "below_min", free_qty: 3, min_qty: 10, deficit: 7, reorder_qty: 20 })],
    };
    render(<WmsAlerts initial={data} />);

    expect(screen.getByText("SKU-1")).toBeInTheDocument();
    expect(screen.getByText("Аккумулятор 18650")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
    expect(screen.getByText("Ниже минимума")).toBeInTheDocument();
  });

  it("пустой title строки выводится как «—»", () => {
    const data: Alerts = { gateway: true, rows: [row({ title: "" })] };
    render(<WmsAlerts initial={data} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("severity out_of_stock даёт лейбл «Нет в наличии»", () => {
    const data: Alerts = { gateway: true, rows: [row({ severity: "out_of_stock" })] };
    render(<WmsAlerts initial={data} />);
    expect(screen.getByText("Нет в наличии")).toBeInTheDocument();
  });

  it("без шлюза кнопка дозаказа disabled, даже если строки есть", () => {
    const data: Alerts = { gateway: false, rows: [row()] };
    render(<WmsAlerts initial={data} />);
    const button = screen.getByRole("button", { name: /Создать заявку в закупку/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Нет нарушенных порогов");
  });

  it("с шлюзом, но без строк кнопка дозаказа disabled", () => {
    const data: Alerts = { gateway: true, rows: [] };
    render(<WmsAlerts initial={data} />);
    expect(screen.getByRole("button", { name: /Создать заявку в закупку/ })).toBeDisabled();
  });

  it("с шлюзом и нарушенными порогами кнопка активна с подсказкой об отправке", () => {
    const data: Alerts = { gateway: true, rows: [row()] };
    render(<WmsAlerts initial={data} />);
    const button = screen.getByRole("button", { name: /Создать заявку в закупку/ });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute("title", "Отправить сигнал дозаказа в закупки");
  });

  it("успешная отправка сигнала показывает тост с числом позиций из ответа", async () => {
    asMock(wh.emitAlerts).mockResolvedValue({ emitted: 4 });
    const data: Alerts = { gateway: true, rows: [row()] };
    render(<WmsAlerts initial={data} />);

    fireEvent.click(screen.getByRole("button", { name: /Создать заявку в закупку/ }));

    expect(await screen.findByText("Сигнал отправлен в закупки, 4 позиции")).toBeInTheDocument();
    expect(wh.emitAlerts).toHaveBeenCalledTimes(1);
  });

  it("неудачная отправка (null от emitAlerts) показывает баннер ошибки", async () => {
    asMock(wh.emitAlerts).mockResolvedValue(null);
    const data: Alerts = { gateway: true, rows: [row()] };
    render(<WmsAlerts initial={data} />);

    fireEvent.click(screen.getByRole("button", { name: /Создать заявку в закупку/ }));

    expect(
      await screen.findByText(
        "Не удалось отправить сигнал — источник остатка (1С) не подключён или сервис недоступен.",
      ),
    ).toBeInTheDocument();
  });

  it("во время загрузки кнопка блокируется до ответа сети", async () => {
    let resolveFn: (v: { emitted: number } | null) => void = () => {};
    asMock(wh.emitAlerts).mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );
    const data: Alerts = { gateway: true, rows: [row()] };
    render(<WmsAlerts initial={data} />);

    const button = screen.getByRole("button", { name: /Создать заявку в закупку/ });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    resolveFn({ emitted: 1 });
    await screen.findByText("Сигнал отправлен в закупки, 1 позиция");
  });
});
