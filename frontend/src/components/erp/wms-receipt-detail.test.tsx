import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WmsReceiptDetail } from "@/components/erp/wms-receipt-detail";
import {
  acceptReceipt,
  fetchReceipt,
  qcReceipt,
  type ReceiptDetail,
} from "@/lib/wms-warehouse";

vi.mock("@/lib/wms-warehouse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/wms-warehouse")>();
  return {
    ...actual,
    acceptReceipt: vi.fn(),
    fetchReceipt: vi.fn(),
    qcReceipt: vi.fn(),
  };
});

const pendingReceipt: ReceiptDetail = {
  qc_revision: "a".repeat(64),
  id: 42,
  number: "RCPT-42",
  source: "purchase_order",
  entity_ref: "PO-7",
  warehouse: "Main",
  status: "pending_qc",
  counterparty: "Supplier",
  created_at: null,
  decided_at: null,
  decided_by: "",
  lines: [
    {
      id: 101,
      sku_code: "SKU-1",
      sku_title: "First item",
      expected_qty: 10,
      accepted_qty: null,
      rejected_qty: null,
      reject_reason: "",
      location_id: null,
      batch_ref: "",
    },
    {
      id: 102,
      sku_code: "SKU-2",
      sku_title: "Second item",
      expected_qty: 5,
      accepted_qty: 3,
      rejected_qty: 0,
      reject_reason: "",
      location_id: null,
      batch_ref: "",
    },
  ],
};

beforeEach(() => {
  vi.mocked(qcReceipt).mockResolvedValue(true);
  vi.mocked(acceptReceipt).mockResolvedValue(true);
  vi.mocked(fetchReceipt).mockResolvedValue(pendingReceipt);
});

afterEach(() => vi.clearAllMocks());

describe("WmsReceiptDetail", () => {
  it("saves QC decisions with the complete normalized payload", async () => {
    render(<WmsReceiptDetail initial={pendingReceipt} />);

    const firstLine = within(screen.getByText("SKU-1").closest("tr")!);
    const [accepted, rejected, reason] = firstLine.getAllByRole("textbox");
    fireEvent.change(accepted, { target: { value: "7,5" } });
    fireEvent.change(rejected, { target: { value: "2" } });
    fireEvent.change(reason, { target: { value: "Damaged" } });

    fireEvent.click(screen.getByRole("button", { name: "Сохранить QC" }));

    await waitFor(() =>
      expect(qcReceipt).toHaveBeenCalledWith(42, [
        { line_id: 101, accepted_qty: "7.5", rejected_qty: "2", reject_reason: "Damaged" },
        { line_id: 102, accepted_qty: "3", rejected_qty: "0", reject_reason: "" },
      ], "", pendingReceipt.qc_revision),
    );
    expect(fetchReceipt).toHaveBeenCalledWith(42);
  });

  it("accepts the receipt after QC has been saved", async () => {
    render(<WmsReceiptDetail initial={pendingReceipt} />);

    const [saveQc, accept] = screen.getAllByRole("button");
    fireEvent.change(screen.getByLabelText("Принято SKU-1"), { target: { value: "0" } });
    fireEvent.click(saveQc);
    await waitFor(() => expect(qcReceipt).toHaveBeenCalledWith(42, expect.any(Array), "", pendingReceipt.qc_revision));

    fireEvent.click(accept);

    await waitFor(() => expect(acceptReceipt).toHaveBeenCalledWith(42));
    expect(qcReceipt.mock.invocationCallOrder[0]).toBeLessThan(acceptReceipt.mock.invocationCallOrder[0]);
    expect(fetchReceipt).toHaveBeenCalledTimes(2);
  });

  it("does not expose QC or acceptance actions for an accepted receipt", () => {
    render(<WmsReceiptDetail initial={{ ...pendingReceipt, status: "accepted" }} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(qcReceipt).not.toHaveBeenCalled();
    expect(acceptReceipt).not.toHaveBeenCalled();
  });

  it("does not send invalid quantities or silently accept unsaved edits", async () => {
    render(<WmsReceiptDetail initial={pendingReceipt} />);
    fireEvent.change(screen.getByLabelText("Принято SKU-1"), { target: { value: "invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить QC" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Введите количество явно");
    expect(qcReceipt).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Принять (приход)" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Сначала сохраните");
    expect(acceptReceipt).not.toHaveBeenCalled();
  });

  it("preserves drafts and unlocks after rejected QC save", async () => {
    vi.mocked(qcReceipt).mockResolvedValue(false);
    render(<WmsReceiptDetail initial={pendingReceipt} />);
    fireEvent.change(screen.getByLabelText("Принято SKU-1"), { target: { value: "7,50" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить QC" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось сохранить");
    expect(screen.getByLabelText("Принято SKU-1")).toHaveValue("7,50");
    expect(screen.getByLabelText("Принято SKU-1")).not.toBeDisabled();
    expect(fetchReceipt).not.toHaveBeenCalled();
  });

  it("reports failed acceptance without claiming a posted receipt", async () => {
    vi.mocked(acceptReceipt).mockResolvedValue(false);
    render(<WmsReceiptDetail initial={pendingReceipt} />);
    fireEvent.click(screen.getByRole("button", { name: "Принять (приход)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось провести");
    expect(fetchReceipt).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Принять (приход)" })).not.toBeDisabled();
  });

  it("explicit comparison refresh preserves drafts and sends the newly viewed revision", async () => {
    vi.mocked(qcReceipt).mockResolvedValue(false);
    const fresh = { ...pendingReceipt, qc_revision: "b".repeat(64), lines: pendingReceipt.lines.map((row) => row.id === 101 ? { ...row, accepted_qty: 8, reject_reason: "Причина другого проверяющего" } : row) };
    vi.mocked(fetchReceipt).mockResolvedValue(fresh);
    render(<WmsReceiptDetail initial={pendingReceipt} />);
    fireEvent.change(screen.getByLabelText("Принято SKU-1"), { target: { value: "7,50" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить QC" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Обновить данные для сравнения" }));
    await screen.findByText("В документе: 8");
    expect(screen.getByText("В документе: Причина другого проверяющего")).toBeVisible();
    expect(screen.getByLabelText("Причина брака SKU-1")).toHaveValue("");
    expect(screen.getByLabelText("Принято SKU-1")).toHaveValue("7,50");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить QC" }));
    await waitFor(() => expect(qcReceipt).toHaveBeenLastCalledWith(42, expect.any(Array), "", fresh.qc_revision));
  });
});
