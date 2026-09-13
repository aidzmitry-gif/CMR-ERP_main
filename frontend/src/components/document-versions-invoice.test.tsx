import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/components/invoice-issuance-dialog", () => ({ openInvoiceIssuance: vi.fn() }));
import { openInvoiceIssuance } from "@/components/invoice-issuance-dialog";
import { DocumentVersions } from "./document-versions";
import { result } from "@/test/invoice-issuance-fixtures";
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("first draft uses exact deal/document ERP dialog", async () => {
  vi.mocked(openInvoiceIssuance).mockResolvedValue(result); const refresh = vi.fn();
  render(<DocumentVersions dealId="1" docs={[{ ...result.document, status: "draft", original_state: "draft" }]} refresh={refresh} />);
  fireEvent.click(screen.getByText("Выпустить версию"));
  await waitFor(() => expect(openInvoiceIssuance).toHaveBeenCalledWith("1", 22));
  expect(refresh).toHaveBeenCalledOnce();
  expect(screen.queryByText("Предпросмотр черновика")).toBeNull();
});
it("replacement stays visibly unsupported and historical original remains", () => {
  render(<DocumentVersions dealId="1" docs={[result.document, { ...result.document, id: 23, status: "draft", original_state: "draft", supersedes_id: 22 }]} refresh={vi.fn()} />);
  expect(screen.getByText("Оригинал #22")).toHaveAttribute("href", "/api/sales/documents/22/render");
  expect(screen.getAllByText(/Замена счёта пока недоступна/)).toHaveLength(2);
  expect(screen.queryByText("Выпустить версию")).toBeNull();
});
