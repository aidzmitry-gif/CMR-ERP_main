import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CounterpartyRelationships } from "./counterparty-relationships";

const request = vi.fn();
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("fetch", request);
});

describe("CounterpartyRelationships", () => {
  it("renders_independent_bounded_contact_deal_call_sections", async () => {
    request.mockImplementation(async (input: string) => {
      const url = new URL(input, "https://example.invalid");
      const kind = url.searchParams.get("kind");
      const base = { counterparty_id: 42, offset: 0, limit: 20, total: 1 };
      if (kind === "contacts") return response({ ...base, kind, items: [{
        id: 7, counterparty_id: 42, full_name: "Synthetic shared contact", phone: "TEST-PHONE-000",
        email: "contact@example.invalid", is_primary: true,
      }] });
      if (kind === "deals") return response({ ...base, kind, items: [{
        id: 77, number: "SYNTHETIC-77", title: "Synthetic deal", counterparty_id: 42,
        crm_client_id: null, stage: "new", owner_id: null, responsible_manager: null,
      }] });
      return response({ ...base, kind, items: [{
        id: 23, call_id: "synthetic-call-23", direction: "in", owner: "Synthetic owner", status: "ended",
        result: "Synthetic result", started_at: "2026-08-01T10:00:00", counterparty_id: 42,
        contact_id: 7, crm_client_id: 420, deal_id: 77,
      }] });
    });
    render(<CounterpartyRelationships counterpartyId={42} focusContactId={7} />);

    expect(await screen.findByText("Synthetic shared contact")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "SYNTHETIC-77 — Synthetic deal" })).toHaveAttribute("href", "/crm/deals/77");
    expect(screen.getByText(/Ответственный: Не назначен/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Открыть звонок" })).toHaveAttribute(
      "href", "/crm/calls?counterparty_id=42&call_id=23#call-23",
    );
    expect(screen.getByRole("link", { name: "Контакт компании" })).toHaveAttribute(
      "href", "/erp/spravochniki/counterparty/42?contact=7#counterparty-contact-7",
    );
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    const urls = request.mock.calls.map(([url]) => new URL(String(url), "https://example.invalid"));
    expect(urls.map((url) => url.searchParams.get("kind")).sort()).toEqual(["calls", "contacts", "deals"]);
    expect(urls.every((url) => url.searchParams.get("limit") === "20")).toBe(true);
    expect(urls.find((url) => url.searchParams.get("kind") === "contacts")?.searchParams.get("contact_id")).toBe("7");
  });

  it("paginates_relationship_sections_without_resetting_other_sections", async () => {
    const firstPageContacts = Array.from({ length: 20 }, (_, index) => ({
      id: 100 + index, counterparty_id: 42, full_name: `Synthetic contact ${index + 1}`,
      phone: null, email: null, is_primary: false,
    }));
    request.mockImplementation(async (input: string) => {
      const url = new URL(input, "https://example.invalid");
      const kind = url.searchParams.get("kind");
      const offset = Number(url.searchParams.get("offset"));
      const base = { counterparty_id: 42, offset, limit: 20 };
      if (kind === "contacts") return response({ ...base, kind, total: 21, items: offset === 0
        ? firstPageContacts : [{ id: 120, counterparty_id: 42, full_name: "Synthetic contact 21",
          phone: null, email: null, is_primary: false }] });
      if (kind === "deals") return response({ ...base, kind, total: 1, items: [{
        id: 77, number: "SYNTHETIC-77", title: "Synthetic retained deal", counterparty_id: 42,
        crm_client_id: null, stage: "new", owner_id: null, responsible_manager: null,
      }] });
      return response({ ...base, kind, total: 0, items: [] });
    });
    render(<CounterpartyRelationships counterpartyId={42} />);
    expect(await screen.findByText("Synthetic contact 1")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "SYNTHETIC-77 — Synthetic retained deal" })).toBeInTheDocument();
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3));

    fireEvent.click(within(screen.getByRole("region", { name: "Контакты компании" }))
      .getByRole("button", { name: "Далее" }));
    expect(await screen.findByText("Synthetic contact 21")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SYNTHETIC-77 — Synthetic retained deal" })).toBeInTheDocument();

    const urls = request.mock.calls.map(([input]) => new URL(String(input), "https://example.invalid"));
    expect(urls.some((url) => url.searchParams.get("kind") === "contacts"
      && url.searchParams.get("offset") === "20" && url.searchParams.get("limit") === "20")).toBe(true);
    expect(urls.filter((url) => url.searchParams.get("kind") === "deals")).toHaveLength(1);
    expect(urls.filter((url) => url.searchParams.get("kind") === "calls")).toHaveLength(1);
  });

  it("recovers_relationship_error_without_leaking_previous_counterparty", async () => {
    let currentContactRequests = 0;
    request.mockImplementation(async (input: string) => {
      const url = new URL(input, "https://example.invalid");
      const match = url.pathname.match(/\/counterparties\/(\d+)\/relationships$/);
      const counterpartyId = Number(match?.[1]);
      const kind = url.searchParams.get("kind");
      const offset = Number(url.searchParams.get("offset"));
      const base = { counterparty_id: counterpartyId, offset, limit: 20 };
      if (kind === "contacts" && counterpartyId === 42) return response({ ...base, kind, total: 1, items: [{
        id: 7, counterparty_id: 42, full_name: "Synthetic prior company contact",
        phone: null, email: null, is_primary: false,
      }] });
      if (kind === "contacts" && counterpartyId === 84) {
        currentContactRequests += 1;
        if (currentContactRequests === 1) return response({ error: "synthetic unavailable" }, 503);
        return response({ ...base, kind, total: 1, items: [{
          id: 8, counterparty_id: 84, full_name: "Synthetic current company contact",
          phone: null, email: null, is_primary: false,
        }] });
      }
      return response({ ...base, kind, total: 0, items: [] });
    });
    const renderCompany = (counterpartyId: number) => <CounterpartyRelationships
      key={counterpartyId} counterpartyId={counterpartyId} />;
    const { rerender } = render(renderCompany(42));
    expect(await screen.findByText("Synthetic prior company contact")).toBeInTheDocument();

    rerender(renderCompany(84));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить связанные записи");
    expect(screen.queryByText("Synthetic prior company contact")).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("region", { name: "Контакты компании" }))
      .getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Synthetic current company contact")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic prior company contact")).not.toBeInTheDocument();

    const contactRequests = request.mock.calls.map(([input]) => new URL(String(input), "https://example.invalid"))
      .filter((url) => url.searchParams.get("kind") === "contacts")
      .map((url) => url.pathname.match(/\/counterparties\/(\d+)\/relationships$/)?.[1]);
    expect(contactRequests).toEqual(["42", "84", "84"]);
  });
});
