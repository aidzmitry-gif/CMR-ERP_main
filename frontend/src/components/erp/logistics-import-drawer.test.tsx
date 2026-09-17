import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/logistics-api", () => ({
  patchImportStage: vi.fn(),
}));

import { ImportDrawer } from "@/components/erp/logistics-import-drawer";
import * as logisticsApi from "@/lib/logistics-api";
import type { ImportShipment } from "@/lib/logistics-api";

const imp: ImportShipment = {
  id: 5,
  number: "IMP-005",
  supplier: "Поставщик",
  flag: "🇨🇳",
  container_no: "CNT-5",
  route: "Шанхай → Минск",
  incoterms: "CIF",
  mode: "sea",
  cargo: "АКБ",
  qty: 12,
  amount: 1250,
  priority: "normal",
  owner: "Иванов",
  stage: "customs",
  customs_status: "Оформляем",
  eta: "2026-09-20",
  po_ref: "PO-5",
};

beforeEach(() => vi.clearAllMocks());

describe("ImportDrawer", () => {
  it("сохраняет статус таможни и продвигает импорт на следующую стадию", async () => {
    const updated = { ...imp, stage: "warehouse", customs_status: "Оформлено" };
    (logisticsApi.patchImportStage as ReturnType<typeof vi.fn>).mockResolvedValue(updated);
    const onUpdated = vi.fn();
    render(<ImportDrawer imp={imp} onClose={vi.fn()} onUpdated={onUpdated} />);

    fireEvent.change(screen.getByPlaceholderText(/Оформляем/), { target: { value: "Оформлено" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить статус" }));
    await waitFor(() =>
      expect(logisticsApi.patchImportStage).toHaveBeenCalledWith(5, {
        stage: "customs",
        customs_status: "Оформлено",
      }),
    );
    expect(onUpdated).toHaveBeenCalledWith(updated);

    fireEvent.click(screen.getByRole("button", { name: /Приёмка на склад/ }));
    await waitFor(() => expect(logisticsApi.patchImportStage).toHaveBeenCalledWith(5, { stage: "warehouse" }));
  });

  it("показывает ошибки API и финальный информационный статус", async () => {
    (logisticsApi.patchImportStage as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    render(<ImportDrawer imp={{ ...imp, stage: "factory", amount: 0 }} onClose={vi.fn()} onUpdated={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Консолидация/ }));
    expect(await screen.findByText("Не удалось продвинуть стадию.")).toBeInTheDocument();

    render(<ImportDrawer imp={{ ...imp, stage: "warehouse" }} onClose={vi.fn()} onUpdated={vi.fn()} />);
    expect(screen.getByText(/учтён в финансах/)).toBeInTheDocument();
    expect(screen.getByText(/Цепочка завершена/)).toBeInTheDocument();
  });
});
