import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DealLinkedDeals } from "./deal-linked-deals";
import {
  loadCounterpartyRelationships,
  type RelatedDeal,
  type RelationshipResult,
} from "@/lib/counterparty-relationships";

vi.mock("@/lib/counterparty-relationships", () => ({ loadCounterpartyRelationships: vi.fn() }));

const load = vi.mocked(loadCounterpartyRelationships);
const relatedDeal = (id: number): RelatedDeal => ({
  id,
  number: `SYNTHETIC-${id}`,
  title: `Synthetic deal ${id}`,
  counterparty_id: 42,
  crm_client_id: null,
  stage: "new",
  owner_id: null,
  responsible_manager: null,
});
const success = (counterpartyId: number, offset: number, total: number, items: RelatedDeal[]): RelationshipResult => ({
  status: "ok",
  page: { kind: "deals", counterparty_id: counterpartyId, offset, limit: 20, total, items },
});

beforeEach(() => vi.resetAllMocks());

describe("DealLinkedDeals", () => {
  it("exact_counterparty_id_no_name_fallback", async () => {
    load.mockResolvedValue(success(42, 0, 1, [relatedDeal(2)]));
    render(<DealLinkedDeals counterpartyId={42} currentId="1" />);

    expect(await screen.findByRole("link", { name: /SYNTHETIC-2 — Synthetic deal 2/ }))
      .toHaveAttribute("href", "/crm/deals/2");
    expect(load).toHaveBeenCalledWith(42, "deals", 0, undefined, expect.any(AbortSignal));
    expect(screen.queryByText(/BYN/)).not.toBeInTheDocument();
  });

  it("excludes_current_deal", async () => {
    load.mockResolvedValue(success(42, 0, 2, [relatedDeal(1), relatedDeal(2)]));
    render(<DealLinkedDeals counterpartyId={42} currentId="1" />);

    expect(await screen.findByRole("link", { name: /SYNTHETIC-2 — Synthetic deal 2/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /SYNTHETIC-1 — Synthetic deal 1/ })).not.toBeInTheDocument();
  });

  it("missing_identity_and_error_are_truthful", async () => {
    load.mockResolvedValueOnce({ status: "error" }).mockResolvedValueOnce({ status: "forbidden" });
    const { rerender } = render(<DealLinkedDeals currentId="1" />);
    expect(screen.getByText("Контрагент не связан с этой сделкой по точному ID.")).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();

    rerender(<DealLinkedDeals counterpartyId={42} currentId="1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить связанные сделки");
    expect(screen.queryByText("Связанных сделок по точному ID не найдено.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа к связанным сделкам");
    expect(load).toHaveBeenLastCalledWith(42, "deals", 0, undefined, expect.any(AbortSignal));
  });

  it("bounded_navigation_to_remaining_deals", async () => {
    const firstPage = [relatedDeal(1), ...Array.from({ length: 19 }, (_, index) => relatedDeal(index + 2))];
    load.mockImplementation(async (counterpartyId, kind, offset) => success(counterpartyId, offset, 21,
      offset === 0 ? firstPage : [relatedDeal(21)]));
    render(<DealLinkedDeals counterpartyId={42} currentId="1" />);

    expect(await screen.findByRole("link", { name: /SYNTHETIC-2 — Synthetic deal 2/ })).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(19);
    expect(screen.getByText("Страница 1 из 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));

    expect(await screen.findByRole("link", { name: /SYNTHETIC-21 — Synthetic deal 21/ }))
      .toHaveAttribute("href", "/crm/deals/21");
    expect(screen.queryByRole("link", { name: /SYNTHETIC-1 — Synthetic deal 1/ })).not.toBeInTheDocument();
    expect(screen.getByText("Страница 2 из 2")).toBeInTheDocument();
    await waitFor(() => expect(load).toHaveBeenLastCalledWith(42, "deals", 20, undefined, expect.any(AbortSignal)));
  });
});
