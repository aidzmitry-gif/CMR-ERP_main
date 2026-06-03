import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDocuments: vi.fn(),
  createDocument: vi.fn(),
  decideDocument: vi.fn(),
}));

import { DealDocuments } from "@/components/deal-documents";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealDocuments", () => {
  it("пустой список → формирование документа (счёт по умолчанию)", async () => {
    mock(api.fetchDocuments).mockResolvedValue([]);
    mock(api.createDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText("Документов пока нет")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocument).toHaveBeenCalledWith("1", "invoice"));
  });

  it("договор на согласовании → проведение в 1С", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      { id: 3, kind: "contract", number: "ДГ-1", status: "pending_approval", onec_ref: null, amount: 1000 },
    ]);
    mock(api.decideDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    expect(await screen.findByText(/ДГ-1/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Согласовать и провести в 1С"));
    await waitFor(() => expect(api.decideDocument).toHaveBeenCalledWith(3, true, "Юрист"));
  });

  it("смена типа документа и отклонение", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      { id: 4, kind: "contract", number: "ДГ-2", status: "pending_approval", onec_ref: null, amount: 1 },
    ]);
    mock(api.createDocument).mockResolvedValue(true);
    mock(api.decideDocument).mockResolvedValue(true);
    render(<DealDocuments dealId="1" />);
    await screen.findByText(/ДГ-2/);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "order" } });
    fireEvent.click(screen.getByText("Сформировать"));
    await waitFor(() => expect(api.createDocument).toHaveBeenCalledWith("1", "order"));
    fireEvent.click(screen.getByTitle("Отклонить"));
    await waitFor(() => expect(api.decideDocument).toHaveBeenCalledWith(4, false, "Юрист"));
  });
});
