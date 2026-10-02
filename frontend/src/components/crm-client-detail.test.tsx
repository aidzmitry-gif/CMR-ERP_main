import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CrmClientDetail } from "./crm-client-detail";
import { callLinkDeal, createDeal, fetchCallsResult, type DealInput, type FetchCallsResult } from "@/lib/api";
import ClientPage from "@/app/crm/clients/[id]/page";
import type { ReactNode } from "react";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("Not found"); } }));
vi.mock("@/components/deal-contacts", () => ({ DealContacts: ({ clientId }: { clientId: number }) => <div>Contacts of {clientId}</div> }));
vi.mock("@/components/kanban/create-deal-modal", () => ({ CreateDealModal: ({ client, onClose, onCreate }: {
  client: { id: number }; onClose: () => void; onCreate: (input: DealInput) => Promise<boolean>;
}) => <div>Deal for {client.id}<button onClick={onClose}>Close draft</button>
  <button onClick={() => void onCreate({ number: "test", title: "test", counterparty: "test", amount: 0, priority: "Средний", stage: "new", owner: "" })}>Save draft</button></div> }));
vi.mock("@/lib/api", () => ({ createDeal: vi.fn(), callLinkDeal: vi.fn(), fetchCallsResult: vi.fn() }));
beforeEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("CrmClientDetail", () => {
  it("shows document versions and links without inventing unavailable originals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(url.endsWith('/documents') ? [
      {id:5,deal_id:7,deal_number:"D7",number:"INV5",kind:"invoice",version:2,original_state:"issued"},
      {id:6,deal_id:7,deal_number:"D7",number:"OLD6",kind:"invoice",version:1,original_state:"legacy_unavailable"},
    ] : url.endsWith('/deals') ? [] : {id:12,name:"Buyer",owner_id:34,unp:null,source:"crm"}))));
    render(<CrmClientDetail clientId={12} />);
    const area = await screen.findByRole("region",{name:"Документы клиента"});
    expect(await within(area).findByRole("link",{name:"Оригинал INV5"})).toHaveAttribute("href","/api/sales/documents/5/render");
    expect(within(area).queryByRole("link",{name:"Оригинал OLD6"})).not.toBeInTheDocument();
    expect(within(area).getByText("INV5 · версия 2")).toBeInTheDocument();
    expect(within(area).getAllByRole("link",{name:"Сделка D7"})[0]).toHaveAttribute("href","/crm/deals/7");
  });

  it("document errors are separate from empty results and can be retried", async () => {
    let failed = true;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith('/documents')
      ? failed ? new Response(null,{status:503}) : Response.json([])
      : Response.json(url.endsWith('/deals') ? [] : {id:12,name:"Buyer",owner_id:34,unp:null,source:"crm"}))));
    render(<CrmClientDetail clientId={12} />);
    const area = await screen.findByRole("region",{name:"Документы клиента"});
    expect(await within(area).findByRole("alert")).toHaveTextContent("Не удалось загрузить документы");
    expect(within(area).queryByText("Документов пока нет.")).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(within(area).getByRole("button",{name:"Обновить документы"}));
    expect(await within(area).findByText("Документов пока нет.")).toBeInTheDocument();
  });

  it("ignores a previous client's late document response", async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal("fetch",vi.fn().mockImplementation((url:string) => {
      if (url.endsWith('/12/documents')) return new Promise(resolve => {finish=resolve;});
      return Promise.resolve(Response.json(url.endsWith('/documents') || url.endsWith('/deals') ? []
        : {id:Number(url.split('/')[4]),name:"Buyer",owner_id:34,unp:null,source:"crm"}));
    }));
    const view = render(<CrmClientDetail clientId={12} />);
    await screen.findByRole("region",{name:"Документы клиента"});
    view.rerender(<CrmClientDetail clientId={13} />);
    await screen.findByText("Документов пока нет.");
    await act(async () => finish(Response.json([{id:5,deal_id:7,deal_number:"D7",number:"OLD-CLIENT",kind:"invoice",version:1,original_state:"issued"}])));
    expect(screen.queryByText(/OLD-CLIENT/)).not.toBeInTheDocument();
  });
  it("closes the draft when navigating from client A to client B", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json((url.endsWith('/deals') || url.endsWith('/documents')) ? []
      : { id: Number(url.split('/').pop()), name: `Buyer ${url.split('/').pop()}`, owner_id: 34, unp: null, source: "crm" }))));
    const view = render(await ClientPage({ params: Promise.resolve({ id: "12" }) }));
    fireEvent.click(await screen.findByRole("button", { name: "Новая сделка клиента" }));
    expect(screen.getByText("Deal for 12")).toBeInTheDocument();
    view.rerender(await ClientPage({ params: Promise.resolve({ id: "13" }) }));
    expect(await screen.findByRole("heading", { name: "Buyer 13" })).toBeInTheDocument();
    expect(screen.queryByText(/Deal for/)).not.toBeInTheDocument();
  });
  it("ignores a late create response after closing and reopening the dialog", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json((url.endsWith('/deals') || url.endsWith('/documents')) ? []
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
    expect(fetch).toHaveBeenCalledTimes(3);
  });
  it("keeps contacts and deal creation available before the first deal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json((url.endsWith('/deals') || url.endsWith('/documents')) ? []
      : { id: 12, name: "Standalone buyer", owner_id: 34, unp: null, source: "crm" }))));
    render(<CrmClientDetail clientId={12} />);
    expect(await screen.findByRole("heading", { name: "Standalone buyer" })).toBeInTheDocument();
    expect(screen.getByText("Contacts of 12")).toBeInTheDocument();
    expect(screen.getByText("Сделок пока нет.")).toBeInTheDocument();
    expect(fetchCallsResult).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Новая сделка клиента" }));
    expect(screen.getByText("Deal for 12")).toBeInTheDocument();
  });

  it("requires an explicit choice among this client's deals and posts that exact deal ID", async () => {
    const call = { id: 51, call_id: "synthetic-51", direction: "in", phone_e164: null, owner: "Тест", status: "ended", result: "Проверка связи", deal_id: null, counterparty_id: 300, started_at: "2026-09-01T10:00:00" };
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(
      url.endsWith("/deals") ? [
        { id: 7, number: "D7", title: "Первая сделка" },
        { id: 8, number: "D8", title: "Вторая сделка" },
      ] : url.endsWith("/documents") ? [] : { id: 12, name: "Buyer", owner_id: 34, unp: null, source: "crm", counterparty_id: 300 },
    ))));
    vi.mocked(fetchCallsResult).mockResolvedValueOnce({ ok: true, rows: [call] })
      .mockResolvedValue({ ok: true, rows: [{ ...call, deal_id: 8 }] });
    vi.mocked(callLinkDeal).mockResolvedValue(true);

    render(<CrmClientDetail clientId={12} />);
    const history = await screen.findByRole("region", { name: "История звонков клиента" });
    const select = await within(history).findByRole("combobox", { name: "Сделка для звонка 51" });
    expect(select).toHaveValue("");
    expect(within(select).getAllByRole("option")).toHaveLength(3);
    expect(within(select).getByRole("option", { name: "D7 — Первая сделка" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "D8 — Вторая сделка" })).toBeInTheDocument();
    const confirm = within(history).getByRole("button", { name: "Привязать звонок 51 к сделке" });
    expect(confirm).toBeDisabled();
    expect(callLinkDeal).not.toHaveBeenCalled();

    fireEvent.change(select, { target: { value: "8" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(callLinkDeal).toHaveBeenCalledWith(51, { deal_id: 8 }));
    expect(await within(history).findByRole("link", { name: "Сделка D8" })).toHaveAttribute("href", "/crm/deals/8");
  });

  it("keeps call history load errors distinct from an empty client history", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json(
      url.endsWith("/deals") || url.endsWith("/documents") ? []
        : { id: 12, name: "Buyer", owner_id: 34, unp: null, source: "crm", counterparty_id: 300 },
    ))));
    vi.mocked(fetchCallsResult).mockResolvedValue({ ok: false, error: "Не удалось загрузить журнал звонков." });
    render(<CrmClientDetail clientId={12} />);

    const history = await screen.findByRole("region", { name: "История звонков клиента" });
    expect(await within(history).findByRole("alert")).toHaveTextContent("Не удалось загрузить журнал звонков");
    expect(within(history).queryByText("Звонков у клиента пока нет.")).not.toBeInTheDocument();
  });

  it("ignores a late call response after navigating to another client", async () => {
    let finishOld!: (value: FetchCallsResult) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      const id = Number(url.split("/")[4]);
      return Promise.resolve(Response.json(url.endsWith("/deals") || url.endsWith("/documents") ? []
        : { id, name: `Buyer ${id}`, owner_id: 34, unp: null, source: "crm", counterparty_id: id + 100 }));
    }));
    vi.mocked(fetchCallsResult).mockImplementation(({ counterparty_id } = {}) => counterparty_id === 112
      ? new Promise<FetchCallsResult>((resolve) => { finishOld = resolve; })
      : Promise.resolve({ ok: true, rows: [{ id: 2, call_id: "synthetic-2", direction: "in", phone_e164: null, owner: "Тест", status: "ended", result: "CLIENT-B-ONLY", deal_id: null, counterparty_id: 113, started_at: "2026-09-01T10:00:00" }] }));

    const view = render(<CrmClientDetail clientId={12} />);
    await screen.findByRole("region", { name: "История звонков клиента" });
    await waitFor(() => expect(fetchCallsResult).toHaveBeenCalledWith({ counterparty_id: 112 }, expect.any(AbortSignal)));
    view.rerender(<CrmClientDetail clientId={13} />);
    expect(await screen.findByText("CLIENT-B-ONLY")).toBeInTheDocument();
    await act(async () => finishOld({ ok: true, rows: [{ id: 1, call_id: "synthetic-1", direction: "in", phone_e164: null, owner: "Тест", status: "ended", result: "CLIENT-A-ONLY", deal_id: null, counterparty_id: 112, started_at: "2026-09-01T09:00:00" }] }));
    expect(screen.queryByText("CLIENT-A-ONLY")).not.toBeInTheDocument();
  });

  it("does not turn an inaccessible client into empty editable data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    render(<CrmClientDetail clientId={99} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Клиент недоступен"));
    expect(screen.queryByRole("button", { name: "Новая сделка клиента" })).not.toBeInTheDocument();
    expect(screen.queryByText("Сделок пока нет.")).not.toBeInTheDocument();
  });
});
