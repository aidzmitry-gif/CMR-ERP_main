import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CrmClientDetail } from "./crm-client-detail";
import { createDeal, type DealInput } from "@/lib/api";
import ClientPage from "@/app/crm/clients/[id]/page";
import type { ReactNode } from "react";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("Not found"); } }));
vi.mock("@/components/deal-contacts", () => ({ DealContacts: ({ clientId }: { clientId: number }) => <div>Contacts of {clientId}</div> }));
vi.mock("@/components/kanban/create-deal-modal", () => ({ CreateDealModal: ({ client, onClose, onCreate }: {
  client: { id: number }; onClose: () => void; onCreate: (input: DealInput) => Promise<boolean>;
}) => <div>Deal for {client.id}<button onClick={onClose}>Close draft</button>
  <button onClick={() => void onCreate({ number: "test", title: "test", counterparty: "test", amount: 0, priority: "Средний", stage: "new", owner: "" })}>Save draft</button></div> }));
vi.mock("@/lib/api", () => ({ createDeal: vi.fn() }));
beforeEach(() => vi.unstubAllGlobals());

describe("CrmClientDetail", () => {
  it("closes the draft when navigating from client A to client B", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(url.endsWith('/deals') ? []
      : { id: Number(url.split('/').pop()), name: `Buyer ${url.split('/').pop()}`, owner_id: 34, unp: null, source: "crm" }))));
    const view = render(await ClientPage({ params: Promise.resolve({ id: "12" }) }));
    fireEvent.click(await screen.findByRole("button", { name: "Новая сделка клиента" }));
    expect(screen.getByText("Deal for 12")).toBeInTheDocument();
    view.rerender(await ClientPage({ params: Promise.resolve({ id: "13" }) }));
    expect(await screen.findByRole("heading", { name: "Buyer 13" })).toBeInTheDocument();
    expect(screen.queryByText(/Deal for/)).not.toBeInTheDocument();
  });
  it("ignores a late create response after closing and reopening the dialog", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(url.endsWith('/deals') ? []
      : { id: 12, name: "Standalone buyer", owner_id: 34, unp: null, source: "crm" }))));
    let finish!: (value: Awaited<ReturnType<typeof createDeal>>) => void;
    vi.mocked(createDeal).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<CrmClientDetail clientId={12} />);
    const open = await screen.findByRole("button", { name: "Новая сделка клиента" });
    fireEvent.click(open);
    fireEvent.click(screen.getByText("Save draft"));
    fireEvent.click(screen.getByText("Close draft"));
    fireEvent.click(open);
    await act(async () => finish({ id: "7" } as Awaited<ReturnType<typeof createDeal>>));
    expect(screen.getByText("Deal for 12")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("keeps contacts and deal creation available before the first deal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(url.endsWith('/deals') ? []
      : { id: 12, name: "Standalone buyer", owner_id: 34, unp: null, source: "crm" }))));
    render(<CrmClientDetail clientId={12} />);
    expect(await screen.findByRole("heading", { name: "Standalone buyer" })).toBeInTheDocument();
    expect(screen.getByText("Contacts of 12")).toBeInTheDocument();
    expect(screen.getByText("Сделок пока нет.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Новая сделка клиента" }));
    expect(screen.getByText("Deal for 12")).toBeInTheDocument();
  });

  it("does not turn an inaccessible client into empty editable data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    render(<CrmClientDetail clientId={99} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Клиент недоступен"));
    expect(screen.queryByRole("button", { name: "Новая сделка клиента" })).not.toBeInTheDocument();
    expect(screen.queryByText("Сделок пока нет.")).not.toBeInTheDocument();
  });
});
