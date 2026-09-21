import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DealDocumentRegister } from "./deal-document-register";
vi.mock("@/components/erp/invoice-cancellation",()=>({InvoiceCancellation:({scope,onCancelled}:{scope:{org:number;deal:number;document:number};onCancelled:()=>void})=><div data-testid="cancellation-scope">{`${scope.org}/${scope.deal}/${scope.document}`}<button onClick={onCancelled}>Тестовое подтверждение отмены</button></div>}));

afterEach(() => vi.unstubAllGlobals());
const row = { id: 100, deal_id: 501, organization_id: 7, kind: "invoice", number: "TEST-100", version: 1, status: "paid", amount: "1200.01", currency: "BYN", created_at: null, issued_at: "2026-09-09", valid_until: null, reserve_status: "consumed", onec_ref: null, original_state: "issued", content_sha256: "sha", replacement_reason: null, supersedes_id: null, superseded_by_id: 101, original_available: true, preview_available: false };
const page = { organization_id: 7, deal_id: 501, client_identity: { status: "unresolved", counterparty_id: null }, coverage: { sales_documents: "available", settlements: "separate_chief_register", shipments: "unavailable", tn_ttn: "not_connected" }, shipment_documents: [], items: [row], next_after_id: null };
const organizations = [{ id: 7, name: "Book A", unp: "111" }, { id: 8, name: "Book B", unp: "222" }];
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
it("opens exact cancellation scope and refreshes selected invoice plus register after success",async()=>{let canceled=false;const fetchMock=vi.fn().mockImplementation((url:string)=>{const current={...row,status:canceled?"cancelled":"posted",reserve_status:canceled?"released":"reserved"};return Promise.resolve(ok(url.includes("document-register?")?{...page,items:[current]}:current));});vi.stubGlobal("fetch",fetchMock);render(<DealDocumentRegister dealId="501" org="7"/>);fireEvent.click(await screen.findByRole("button",{name:"Открыть версию ID 100"}));fireEvent.click(await screen.findByRole("button",{name:"Аннулирование счёта"}));expect(screen.getByTestId("cancellation-scope")).toHaveTextContent("7/501/100");canceled=true;fireEvent.click(screen.getByRole("button",{name:"Тестовое подтверждение отмены"}));await screen.findAllByText(/Аннулирован · Резерв снят/);expect(fetchMock.mock.calls.filter(([url])=>url.includes("document-register?")).length).toBe(2);expect(fetchMock.mock.calls.filter(([url])=>url.endsWith("document-register/100")).length).toBe(2);});
function deferred() { let resolve!: (v: unknown) => void; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve: (v: unknown) => resolve(v) }; }
async function selectBook() { await screen.findByRole("option", { name: "Book A · 111" }); fireEvent.change(screen.getByLabelText("Юрлицо реестра"), { target: { value: "7" } }); }

it("requires explicit book selection and shows honest coverage and reserve semantics", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(organizations)).mockResolvedValueOnce(ok(page)); vi.stubGlobal("fetch", fetchMock);
  render(<DealDocumentRegister dealId="501" />); await screen.findByRole("option", { name: "Book A · 111" });
  expect(screen.getByLabelText("Юрлицо реестра")).toHaveValue(""); expect(fetchMock).toHaveBeenCalledOnce();
  await selectBook(); await screen.findByText("1200.01 BYN");
  expect(screen.getByText(/Исторический статус резерва: требуется сверка/)).toBeInTheDocument(); expect(screen.queryByText(/исполнен отгрузкой|Резерв → оплачен/)).not.toBeInTheDocument();
  expect(screen.getByText(/Клиент сделки ещё не подтверждён/)).toBeInTheDocument(); expect(screen.getByText(/не означает отсутствия отгрузок/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /отмен|подтвердить|выпустить/i })).not.toBeInTheDocument();
});

it("shows an unavailable 1C link without inventing an external reference", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...page, items: [{ ...row, status: "posted", onec_ref: null }] })));
  render(<DealDocumentRegister dealId="501" org="7" />);
  expect(await screen.findByText("Связь с 1С не подтверждена.")).toBeInTheDocument();
  expect(screen.queryByText(/Ссылка 1С:/)).toBeNull();
});

it("uses scoped lookup for linked versions outside the current filter/page and opens saved HTML in a sandbox", async () => {
  const next = { ...row, id: 101, number: "TEST-101", supersedes_id: 100, superseded_by_id: null };
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(page)).mockResolvedValueOnce(ok(next)).mockResolvedValueOnce({ ok: true, status: 200, headers: new Headers({ "Content-Type": "text/html" }), text: async () => "<p>Saved original 101</p>" }); vi.stubGlobal("fetch", fetchMock);
  render(<DealDocumentRegister dealId="501" org="7" />); fireEvent.click(await screen.findByRole("button", { name: "Заменён ID 101" }));
  fireEvent.click(await screen.findByRole("button", { name: "Открыть оригинал ID 101" }));
  const frame = await screen.findByTitle("Сохранённый оригинал ID 101"); expect(frame).toHaveAttribute("sandbox", ""); expect(frame).toHaveAttribute("srcdoc", "<p>Saved original 101</p>");
  expect(fetchMock.mock.calls[1][0]).toBe("/api/sales/organizations/7/deals/501/document-register/101");
  expect(fetchMock.mock.calls[2][0]).toBe("/api/sales/organizations/7/deals/501/documents/101/original");
  fireEvent.click(screen.getByRole("button", { name: "Закрыть версию" })); expect(screen.queryByLabelText("Выбранная версия")).not.toBeInTheDocument();
});

it("paginates once per click burst without dropping earlier versions", async () => {
  const pending = deferred(); const fetchMock = vi.fn().mockResolvedValueOnce(ok({ ...page, next_after_id: 100 })).mockReturnValueOnce(pending.promise); vi.stubGlobal("fetch", fetchMock);
  render(<DealDocumentRegister dealId="501" org="7" />); const button = await screen.findByRole("button", { name: "Ещё документы" });
  act(() => { fireEvent.click(button); fireEvent.click(button); }); expect(fetchMock).toHaveBeenCalledTimes(2);
  await act(async () => pending.resolve(ok({ ...page, items: [{ ...row, id: 101 }] })));
  expect(screen.getByLabelText("Версия документа 100")).toBeInTheDocument(); expect(screen.getByLabelText("Версия документа 101")).toBeInTheDocument(); expect(fetchMock.mock.calls[1][0]).toContain("after_id=100");
});

it.each(["organization", "deal", "filter"])("ignores late old register response after %s change", async (kind) => {
  const pending = deferred(); const fetchMock = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok({ ...page, organization_id: kind === "organization" ? 8 : 7, deal_id: kind === "deal" ? 502 : 501, items: [] })); vi.stubGlobal("fetch", fetchMock);
  const view = render(<DealDocumentRegister dealId="501" org="7" />);
  if (kind === "filter") fireEvent.change(screen.getByLabelText("Вид документа реестра"), { target: { value: "contract" } });
  else view.rerender(<DealDocumentRegister dealId={kind === "deal" ? "502" : "501"} org={kind === "organization" ? "8" : "7"} />);
  await screen.findByText("В этом реестре документы по фильтру не найдены.");
  await act(async () => pending.resolve(ok(page))); expect(screen.queryByText("1200.01 BYN")).not.toBeInTheDocument();
});

it("ignores a late lookup failure after selecting another version and a late original after closing", async () => {
  const lookup = deferred(), original = deferred();
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(page)).mockReturnValueOnce(lookup.promise).mockResolvedValueOnce(ok(row)).mockReturnValueOnce(original.promise); vi.stubGlobal("fetch", fetchMock);
  render(<DealDocumentRegister dealId="501" org="7" />); fireEvent.click(await screen.findByRole("button", { name: "Заменён ID 101" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть версию ID 100" })); await screen.findByRole("button", { name: "Открыть оригинал ID 100" });
  await act(async () => lookup.resolve({ ok: false, status: 403 })); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть оригинал ID 100" })); fireEvent.click(screen.getByRole("button", { name: "Закрыть оригинал" }));
  await act(async () => original.resolve({ ok: true, headers: new Headers({ "Content-Type": "text/html" }), text: async () => "stale" }));
  expect(screen.queryByTitle("Сохранённый оригинал ID 100")).not.toBeInTheDocument();
});

it.each([403, 404, 409, 503])("shows GET %s without claiming the deal has no documents", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status })); render(<DealDocumentRegister dealId="501" org="7" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.queryByText("В этом реестре документы по фильтру не найдены.")).not.toBeInTheDocument();
});

it("does not offer an original for drafts or legacy, and never substitutes preview after 409", async () => {
  const draft = { ...row, id: 102, original_state: "draft", status: "draft", original_available: false };
  const legacy = { ...row, id: 103, original_state: "legacy_unavailable", currency: null, original_available: false };
  const fetchMock = vi.fn().mockResolvedValueOnce(ok({ ...page, items: [row, draft, legacy] })).mockResolvedValueOnce(ok(legacy)).mockResolvedValueOnce(ok(row)).mockResolvedValueOnce({ ok: false, status: 409 }); vi.stubGlobal("fetch", fetchMock);
  render(<DealDocumentRegister dealId="501" org="7" />); fireEvent.click(await screen.findByRole("button", { name: "Открыть версию ID 103" }));
  await screen.findByLabelText("Выбранная версия"); expect(within(screen.getByLabelText("Выбранная версия")).queryByRole("button", { name: /Открыть оригинал/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть версию ID 100" })); fireEvent.click(await screen.findByRole("button", { name: "Открыть оригинал ID 100" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("409:"); expect(fetchMock.mock.calls.some(([url]) => url.includes("preview"))).toBe(false);
});

it("does not call an API for invalid deal identity and separates book errors from no available books", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 403 }); vi.stubGlobal("fetch", fetchMock);
  const view = render(<DealDocumentRegister dealId="" />); expect(fetchMock).not.toHaveBeenCalled();
  view.rerender(<DealDocumentRegister dealId="501" />); expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(screen.queryByText("Доступных книг нет.")).not.toBeInTheDocument();
});

it.each(["issued", "paid", "cancelled"])("expiry reminder is visible only for an active reserved invoice: %s", async status => {
  const warned = {...row, status, reserve_status: "reserved", superseded_by_id: null, expiry_reminder_at: "2026-09-10T12:00:00Z"};
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({...page, items: [warned]})));
  render(<DealDocumentRegister dealId="501" org="7" />);
  await screen.findByLabelText("Версия документа 100");
  const warning = screen.queryByText(/Требуется проверка срока действия счёта/);
  if (status === "issued") {
    expect(warning).toBeInTheDocument();
    expect(warning).toHaveTextContent("Резерв сохранён");
  } else expect(warning).not.toBeInTheDocument();
});

it("deep-links directly to an exact invoice without cancelling it automatically", async () => {
  const fetcher = vi.fn(async (url: string) => ok(url.endsWith("document-register/100") ? row : page));
  vi.stubGlobal("fetch", fetcher);
  render(<DealDocumentRegister dealId="501" org="7" initialDocumentId={100} />);
  await screen.findByRole("button", { name: "Аннулирование счёта" });
  expect(fetcher.mock.calls.some(([url]) => url === "/api/sales/organizations/7/deals/501/document-register/100")).toBe(true);
  expect(screen.queryByTestId("cancellation-scope")).not.toBeInTheDocument();
});
it("does not open cancellation for a forged invoice deep-link response", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ok(url.endsWith("document-register/100") ? { ...row, deal_id: 999 } : page)));
  render(<DealDocumentRegister dealId="501" org="7" initialDocumentId={100} />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("button", { name: "Аннулирование счёта" })).not.toBeInTheDocument();
});
