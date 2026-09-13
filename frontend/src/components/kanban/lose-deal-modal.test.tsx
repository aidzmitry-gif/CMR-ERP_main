import { webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { hash, type InvoiceProgress, type LossRecord, type LossResolution, type LossSnapshot,
  type ResolveBody } from "@/lib/deal-loss-api";
import { LoseDealModal } from "./lose-deal-modal";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ fetchLossReasons: vi.fn().mockResolvedValue([{ code: "price", title: "Цена" }]) }));
beforeEach(() => { sessionStorage.clear(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const ok = (v: unknown) => ({ ok: true, status: 200, json: async () => v });
const reasons = [{ code: "price", title: "Цена" }];
async function server(invoices = false) {
  const snapshot: LossSnapshot = { funnel: "repeat_clients", stage: "rp_new", lost_stage: "rp_lost", invoices: invoices
    ? [{ id: 4, deal_id: 1, kind: "invoice", version: 2, content_sha256: "a".repeat(64), supersedes_id: 3, superseded_by_id: null }] : [] };
  const s = { principal: "seller", unowned: false, lostReply: false, record: null as LossRecord | null,
    ready: !invoices, posts: [] as { url: string; body: string }[] };
  const rows = (): InvoiceProgress[] => invoices ? [{ document_id: 4, status: s.ready ? "cancelled" : "paid", reserve_status: s.ready ? "released" : "reserved",
    ready: s.ready, blockers: s.ready ? [] : ["funds_not_fully_refunded"], money: { state: s.ready ? "fully_refunded" : "funds_held", digest: "b".repeat(64), received: "100.00", refunded: s.ready ? "100.00" : "0.00" } }] : [];
  async function resolve(body: ResolveBody, action: "finalized" | "withdrawn") {
    const r = s.record!;
    const base = { id: body.request_key, request_id: r.request_id, action, command: body, command_hash: await hash(body), actor: s.principal,
      snapshot: { organization_id: 7, deal_id: 1, request_digest: r.request_digest, from_stage: snapshot.stage,
        to_stage: action === "finalized" ? snapshot.lost_stage! : snapshot.stage, funnel: snapshot.funnel, composition: snapshot.invoices, invoices: rows() } };
    const receipt: LossResolution = { ...base, resolution_id: base.id, digest: await hash(base) };
    s.record = { ...r, state: action, resolution: receipt, ready_to_finalize: false, invoices: rows() };
    return receipt;
  }
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("loss-context")) return ok({ deal_id: 1, principal: s.principal, organization_id: s.unowned ? null : 7,
      organization: s.unowned ? null : { id: 7, name: "Подтверждённая компания", unp: "123" }, mapping_required: s.unowned,
      funnel: snapshot.funnel, stage: s.record?.state === "finalized" ? snapshot.lost_stage : snapshot.stage,
      lost_stage: snapshot.lost_stage, pending_request_id: s.record?.state === "pending" ? s.record.request_id : null,
      latest_request_id: s.record?.request_id ?? null, latest_request_state: s.record?.state ?? null });
    if (url.endsWith("loss-preview")) return ok({ organization_id: 7, deal_id: 1, snapshot, composition_digest: await hash(snapshot),
      pending_request_id: s.record?.state === "pending" ? s.record.request_id : null, invoices: rows() });
    if (!options?.method) return s.record ? ok({ ...s.record, invoices: rows(), ready_to_finalize: s.record.state === "pending" && s.ready }) : { ok: false, status: 404 };
    s.posts.push({ url, body: String(options.body) });
    const body = JSON.parse(String(options.body));
    if (url.endsWith("/lose")) {
      if (!s.record || s.record.state === "withdrawn") {
        const base = { id: body.request_key, organization_id: 7, deal_id: 1, command: body, command_hash: await hash(body), snapshot, actor: s.principal };
        s.record = { ...base, request_id: base.id, request_digest: await hash(base), state: "pending", resolution: null, invoices: rows(), ready_to_finalize: s.ready };
        if (body.finalize_if_empty && !invoices) await resolve({ request_key: body.request_key, expected_request_digest: s.record.request_digest, evidence: "Explicit finalize_if_empty request" }, "finalized");
      }
      if (s.lostReply) { s.lostReply = false; throw new Error("Lost response after commit"); }
      return ok(s.record);
    }
    return ok(await resolve(body, url.endsWith("/finalize") ? "finalized" : "withdrawn"));
  });
  vi.stubGlobal("fetch", fetcher);
  return { s, fetcher, snapshot };
}
async function submit() {
  await screen.findByLabelText("Причина отказа");
  fireEvent.change(screen.getByLabelText("Причина отказа"), { target: { value: "price" } });
  fireEvent.click(screen.getByRole("button", { name: "Запросить отказ" }));
  await screen.findByLabelText("Основание завершения или отзыва");
}
it("keeps pending on its stage; only exact finalized receipt invokes completion", async () => {
  const { s } = await server(); const done = vi.fn();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} onFinalized={done} />);
  await submit(); expect(done).not.toHaveBeenCalled();
  expect(screen.getByText(/остаётся на исходной стадии/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Основание завершения или отзыва"), { target: { value: "Все счета проверены" } });
  fireEvent.click(screen.getByRole("button", { name: "Завершить отказ" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(done.mock.calls[0][0].snapshot.to_stage).toBe("rp_lost");
  expect(s.posts).toHaveLength(2);
});
it("shows paid/full-refund blockers and provides exact scoped invoice link", async () => {
  const { s } = await server(true);
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await submit();
  expect(screen.getByRole("button", { name: "Завершить отказ" })).toBeDisabled();
  expect(screen.getByText(/Деньги ещё не возвращены полностью/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Открыть счёт и аннулирование" })).toHaveAttribute("href", "/crm/deals/1?org=7&invoice=4#document-register");
  expect(s.posts.every(p => !/cancel|refund|review/.test(p.url))).toBe(true);
  s.ready = true; fireEvent.click(screen.getByRole("button", { name: "Обновить сведения" }));
  await screen.findByText(/Полный возврат подтверждён/);
  fireEvent.change(screen.getByLabelText("Основание завершения или отзыва"), { target: { value: "Отмены подтверждены" } });
  expect(screen.getByRole("button", { name: "Завершить отказ" })).toBeEnabled();
});
it("does not select an organization for an unowned deal", async () => {
  const { s } = await server(); s.unowned = true;
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await screen.findByText(/Юрлицо сделки не подтверждено/);
  expect(screen.queryByRole("button", { name: "Запросить отказ" })).not.toBeInTheDocument();
  expect(s.posts).toHaveLength(0);
});
it("requires explicit empty finalize flag", async () => {
  const { s } = await server(); const done = vi.fn();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} onFinalized={done} />);
  await screen.findByLabelText("Причина отказа");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Причина отказа"), { target: { value: "price" } });
  fireEvent.click(screen.getByRole("checkbox")); fireEvent.click(screen.getByRole("button", { name: "Запросить отказ" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(JSON.parse(s.posts[0].body).finalize_if_empty).toBe(true);
});
it("recovers a committed request after lost response and remount without a second POST", async () => {
  const { s } = await server(); s.lostReply = true;
  const view = render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await screen.findByLabelText("Причина отказа");
  fireEvent.change(screen.getByLabelText("Причина отказа"), { target: { value: "price" } });
  fireEvent.click(screen.getByRole("button", { name: "Запросить отказ" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить результат команды" })).toBeEnabled()); view.unmount();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить результат команды" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Проверить результат команды" }));
  await screen.findByLabelText("Основание завершения или отзыва"); expect(s.posts).toHaveLength(1);
});
it("withdrawal keeps invoice cancellation and a later request gets a new UUID", async () => {
  const { s } = await server(true); s.ready = true;
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await submit(); const first = s.record!.request_id;
  fireEvent.change(screen.getByLabelText("Основание завершения или отзыва"), { target: { value: "Продолжим переговоры" } });
  fireEvent.click(screen.getByRole("button", { name: "Отозвать запрос" }));
  fireEvent.click(await screen.findByRole("button", { name: "Подготовить новый запрос" }));
  await submit(); expect(s.record!.request_id).not.toBe(first);
  expect(screen.getByText(/Статус: cancelled/)).toBeInTheDocument();
});
it("does not dispatch under a changed principal", async () => {
  const { s } = await server();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
  await screen.findByLabelText("Причина отказа");
  fireEvent.change(screen.getByLabelText("Причина отказа"), { target: { value: "price" } });
  s.principal = "other"; fireEvent.click(screen.getByRole("button", { name: "Запросить отказ" }));
  await screen.findByText(/Пользователь или юрлицо изменились/); expect(s.posts).toHaveLength(0);
});
it("a late old mount context cannot restore an A-B-A screen", async () => {
  const { fetcher } = await server(); let late!: (value: unknown) => void;
  fetcher.mockImplementationOnce(() => new Promise(resolve => { late = resolve; }));
  const view = render(<LoseDealModal dealId="1" dealLabel="A first" reasons={reasons} onCancel={vi.fn()} />);
  view.unmount();
  render(<LoseDealModal dealId="1" dealLabel="A new mount" reasons={reasons} onCancel={vi.fn()} />);
  await screen.findByLabelText("Причина отказа");
  await act(async () => late(ok({ bad: true })));
  expect(screen.getByText("A new mount")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it.each(["preview", "progress"])("does not publish old-principal %s after an in-place identity change", async source => {
  const { s, fetcher } = await server();
  if (source === "progress") {
    const initial = render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} />);
    await submit(); initial.unmount();
  }
  const original = fetcher.getMockImplementation()!;
  let release!: () => void;
  fetcher.mockImplementation(async (url, options) => {
    const response = await original(url, options);
    if ((source === "preview" && url.endsWith("loss-preview"))
      || (source === "progress" && url.includes("/loss-requests/") && !options?.method)) {
      await new Promise<void>(resolve => { release = resolve; });
    }
    return response;
  });
  const pending = vi.fn(); const done = vi.fn();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} onPending={pending} onFinalized={done} />);
  await waitFor(() => expect(release).toBeTypeOf("function"));
  s.principal = "another";
  await act(async () => release());
  await screen.findByText(/Пользователь или юрлицо изменились/);
  expect(screen.queryByText(/Учётная запись: seller/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Причина отказа")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Основание завершения или отзыва")).not.toBeInTheDocument();
  expect(pending).not.toHaveBeenCalled(); expect(done).not.toHaveBeenCalled();
});
it("publishes finalized history even when a new monetary preview is unavailable", async () => {
  const { s, fetcher } = await server();
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (url, options) => {
    if (s.record && url.endsWith("loss-preview")) return { ok: false, status: 503 };
    return original(url, options);
  });
  const done = vi.fn();
  render(<LoseDealModal dealId="1" dealLabel="Сделка 1" reasons={reasons} onCancel={vi.fn()} onFinalized={done} />);
  await submit();
  fireEvent.change(screen.getByLabelText("Основание завершения или отзыва"), { target: { value: "Проверено" } });
  fireEvent.click(screen.getByRole("button", { name: "Завершить отказ" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(screen.getByText(/отказ завершён/)).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith("loss-preview"))).toHaveLength(1);
});
