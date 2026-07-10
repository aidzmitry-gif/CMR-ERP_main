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
        { line_id: 101, accepted_qty: 7.5, rejected_qty: 2, reject_reason: "Damaged" },
        { line_id: 102, accepted_qty: 3, rejected_qty: 0, reject_reason: "" },
      ]),
    );
    expect(fetchReceipt).toHaveBeenCalledWith(42);
  });

  it("accepts the receipt after QC has been saved", async () => {
    render(<WmsReceiptDetail initial={pendingReceipt} />);

    const [saveQc, accept] = screen.getAllByRole("button");
    fireEvent.click(saveQc);
    await waitFor(() => expect(qcReceipt).toHaveBeenCalledWith(42, expect.any(Array)));

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
});
