import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/lib/api", () => ({ fetchDocuments: vi.fn(), createDocumentResult: vi.fn(), decideDocument: vi.fn() }));
vi.mock("@/components/document-versions", () => ({ DocumentVersions: () => null }));
import { createDocumentResult, fetchDocuments } from "@/lib/api";
import { DealDocuments } from "./deal-documents";
import { result } from "@/test/invoice-issuance-fixtures";
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("shows load failure without claiming there are no documents", async () => {
  vi.mocked(fetchDocuments).mockRejectedValue(new Error("Нет доступа"));
  render(<DealDocuments dealId="1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить документы");
  expect(screen.queryByText("Документов пока нет")).toBeNull();
  expect(fetchDocuments).toHaveBeenCalledWith("1", { throwOnError: true });
});
it("labels local issued document correctly", async () => {
  vi.mocked(fetchDocuments).mockResolvedValue([result.document]);
  render(<DealDocuments dealId="1" />);
  expect(await screen.findByText("Выпущен")).toBeInTheDocument();
  expect(screen.queryByText("Записан в 1С")).toBeNull();
});
it("does not show another deal's late document list", async () => {
  let resolve!: (value: typeof result.document[]) => void;
  vi.mocked(fetchDocuments).mockImplementation(id => id === "1" ? new Promise(r => { resolve = r; }) : Promise.resolve([]));
  const view = render(<DealDocuments dealId="1" />);
  view.rerender(<DealDocuments dealId="2" />);
  await act(async () => resolve([result.document]));
  expect(screen.queryByText(/ERP-INV-22/)).toBeNull();
  expect(await screen.findByText("Документов пока нет")).toBeInTheDocument();
});

it.each([false, true])("restores enabled invoice opener without stealing a new focus (%s)", async movedFocus => {
  let finish!: (value: { doc: null }) => void;
  vi.mocked(fetchDocuments).mockResolvedValue([]);
  vi.mocked(createDocumentResult).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<><input aria-label="Другой элемент" /><DealDocuments dealId="1" /></>);
  await screen.findByText("Документов пока нет");
  const opener = screen.getByRole("button", { name: "Сформировать" });
  opener.focus();
  fireEvent.click(opener);
  expect(opener).toBeDisabled();
  opener.blur();
  const other = screen.getByLabelText("Другой элемент");
  if (movedFocus) other.focus();
  await act(async () => finish({ doc: null }));
  expect(opener).toBeEnabled();
  expect(movedFocus ? other : opener).toHaveFocus();
});
