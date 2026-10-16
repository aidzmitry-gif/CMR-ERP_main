import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingSellerProfiles } from "./accounting-seller-profiles";
import { createSellerProfile, fetchSellerCurrent, fetchSellerHistory, sellerKey, type SellerProfile, type SellerRequest } from "@/lib/seller-profiles-api";

afterEach(() => vi.unstubAllGlobals());
const seller = { name: "Историческое имя", unp: "123456789", currency: "BYN", address: "Адрес", account: "BY-ACCOUNT", bank: "Банк", bik: "BIK", director: "Руководитель", phone: "", email: "", logo_data_url: "", stamp_data_url: null, signature_data_url: null };
const row: SellerProfile = { organization_id: 7, profile_id: 5, revision: 5, effective_from: "2026-09-01", digest: "a".repeat(64), seller, evidence: "Архивное основание", actor: "chief" };
const body: SellerRequest = { source_key: "unused", expected_revision: 5, effective_from: "2026-10-01", currency: "BYN", address: "Новый адрес", account: "NEW-ACCOUNT", bank: "Новый банк", bik: "NEW-BIK", director: "Новый руководитель", phone: "", email: "", evidence: "Первичный документ", confirmed: true };
const saved: SellerProfile = { ...row, profile_id: 6, revision: 6, effective_from: body.effective_from, seller: { ...seller, name: "Сохранённое сервером имя", address: body.address, account: body.account, bank: body.bank, bik: body.bik, director: body.director }, evidence: body.evidence };
const ok = (v: unknown) => ({ ok: true, status: 200, json: async () => v });
const fail = (status: number) => ({ ok: false, status });
function deferred() { let resolve!: (v: unknown) => void; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; }
async function draft() {
  const prepare = await screen.findByRole("button", { name: "Подготовить новую версию реквизитов" });
  await waitFor(() => expect(prepare).toBeEnabled()); fireEvent.click(prepare);
  for (const [label, value] of [["Начало действия реквизитов", body.effective_from], ["Валюта новой версии", body.currency], ["Адрес продавца", body.address], ["Расчётный счёт", body.account], ["Банк продавца", body.bank], ["БИК", body.bik], ["Руководитель", body.director], ["Основание реквизитов", body.evidence]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText("Реквизиты проверены главным бухгалтером"));
}
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Подтвердить версию реквизитов" }));
function query(currency = "BYN") { fireEvent.change(screen.getByLabelText("Дата действующих реквизитов"), { target: { value: "2026-09-15" } }); fireEvent.change(screen.getByLabelText("Валюта действующих реквизитов"), { target: { value: currency } }); fireEvent.click(screen.getByRole("button", { name: "Показать действующие реквизиты" })); }

it("explicit date/currency, historical snapshot and server-owned readonly organization", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok(row)); vi.stubGlobal("fetch", f);
  render(<AccountingSellerProfiles org="7" organization={{ name: "Текущее имя", unp: "123456789" }} />);
  await screen.findByLabelText("Историческая версия 5"); expect(screen.getByText(/Историческое имя/)).toBeInTheDocument(); expect(screen.getByText(/Текущее имя/)).toBeInTheDocument(); expect(screen.getByLabelText("Дата действующих реквизитов")).toHaveValue(""); expect(screen.getByLabelText("Валюта действующих реквизитов")).toHaveValue(""); expect(f).toHaveBeenCalledOnce();
  query(); await screen.findByLabelText("Действует на 2026-09-15: версия 5"); expect(f.mock.calls[1][0]).toBe("/api/accounting/organizations/7/seller-profile?on=2026-09-15&currency=BYN"); expect(screen.queryByLabelText(/УНП|Наименование/)).not.toBeInTheDocument();
});
it("global latest revision differs from dated/currency profile and automatic key is not a user field", async () => {
  const latest = { ...row, seller: { ...seller, currency: "USD" }, effective_from: "2027-01-01" };
  const f = vi.fn().mockResolvedValueOnce(ok([latest])).mockResolvedValueOnce(ok({ ...row, revision: 2, profile_id: 2 })).mockResolvedValueOnce(ok([latest])).mockResolvedValueOnce(ok(saved)).mockResolvedValue(ok([saved])); vi.stubGlobal("fetch", f); vi.stubGlobal("crypto", { randomUUID: () => "native-key-1" });
  render(<AccountingSellerProfiles org="7" />); await screen.findByLabelText("Историческая версия 5"); query(); await screen.findByLabelText("Действует на 2026-09-15: версия 2"); await draft(); submit(); await screen.findByLabelText("Фактически сохранена версия 6");
  const posted = JSON.parse(f.mock.calls.find(([, init]) => init?.method === "POST")![1].body); expect(posted.expected_revision).toBe(5); expect(posted.source_key).toBe("native-key-1"); expect(posted).not.toHaveProperty("actor"); expect(posted).not.toHaveProperty("name"); expect(posted).not.toHaveProperty("unp"); expect(screen.queryByLabelText(/Ключ/)).not.toBeInTheDocument();
});
it("valid empty history uses revision zero", async () => {
  const first = { ...saved, revision: 1 }; const f = vi.fn().mockResolvedValueOnce(ok([])).mockResolvedValueOnce(ok([])).mockResolvedValueOnce(ok(first)).mockResolvedValueOnce(ok([first])); vi.stubGlobal("fetch", f);
  render(<AccountingSellerProfiles org="7" />); await screen.findByText("Подтверждённых версий реквизитов пока нет."); await draft(); submit(); await screen.findByLabelText("Фактически сохранена версия 1"); expect(JSON.parse(f.mock.calls[2][1].body).expected_revision).toBe(0);
});
it.each([403, 404, 409, 503])("history %s never becomes empty baseline zero", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fail(status))); render(<AccountingSellerProfiles org="7" />); expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.queryByText("Подтверждённых версий реквизитов пока нет.")).not.toBeInTheDocument(); expect(screen.getByRole("button", { name: "Подготовить новую версию реквизитов" })).toBeDisabled();
});
it.each(["BYN", "ZZZ", "USD"])("current %s failure preserves historical snapshots", async (currency) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(fail(409))); render(<AccountingSellerProfiles org="7" />); await screen.findByLabelText("Историческая версия 5"); query(currency); expect(await screen.findByRole("alert")).toHaveTextContent("409:"); expect(screen.getByLabelText("Историческая версия 5")).toBeInTheDocument();
});
it("changed global revision preflight prevents POST and unchecks confirmation", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([{ ...row, profile_id: 9, revision: 9, seller: { ...seller, currency: "EUR" } }])); vi.stubGlobal("fetch", f); const busy = vi.fn(); render(<AccountingSellerProfiles org="7" onBusyChange={busy} />); await draft(); submit(); await screen.findByText(/Глобальная версия юрлица изменилась/); expect(f.mock.calls.every(([, init]) => init.method === "GET")).toBe(true); expect(screen.getByLabelText("Реквизиты проверены главным бухгалтером")).not.toBeChecked(); expect(busy).toHaveBeenLastCalledWith(false);
});
it.each([403, 409, 422])("first POST %s requires fresh basis", async (status) => {
  const f = vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(fail(status)).mockResolvedValueOnce(ok([row])); vi.stubGlobal("fetch", f); const busy = vi.fn(); render(<AccountingSellerProfiles org="7" onBusyChange={busy} />); await draft(); submit(); expect(await screen.findByRole("alert")).toHaveTextContent(`${status}:`); expect(screen.getByRole("button", { name: "Подтвердить версию реквизитов" })).toBeDisabled(); expect(busy).toHaveBeenLastCalledWith(false); fireEvent.click(screen.getByRole("button", { name: "Обновить основу версии" })); await waitFor(() => expect(f).toHaveBeenCalledTimes(4)); expect(screen.getByLabelText("Реквизиты проверены главным бухгалтером")).not.toBeChecked();
});
it.each(["network", "5xx", "malformed"])("%s freezes payload, retry403 remains unknown, exact replay succeeds", async (kind) => {
  const f = vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([row])); if (kind === "network") f.mockRejectedValueOnce(new Error("offline")); else f.mockResolvedValueOnce(kind === "5xx" ? fail(503) : ok({ profile_id: 6 }));
  f.mockResolvedValueOnce(fail(403)).mockResolvedValueOnce(ok(saved)).mockResolvedValueOnce(ok([saved])); vi.stubGlobal("fetch", f); const busy = vi.fn(); render(<AccountingSellerProfiles org="7" onBusyChange={busy} />); await draft(); submit(); fireEvent.click(await screen.findByRole("button", { name: "Повторить сохранённый запрос" })); expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(busy).toHaveBeenLastCalledWith(true); expect(screen.getByLabelText("Адрес продавца")).toBeDisabled(); expect(screen.getByLabelText("Дата действующих реквизитов")).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "Повторить сохранённый запрос" })); await screen.findByLabelText("Фактически сохранена версия 6"); const posts = f.mock.calls.filter(([, init]) => init.method === "POST"); expect(posts).toHaveLength(3); expect(new Set(posts.map(([, init]) => init.body)).size).toBe(1); expect(busy).toHaveBeenLastCalledWith(false);
});
it("double-click sends one preflight and POST", async () => {
  const pending = deferred(); const f = vi.fn().mockResolvedValueOnce(ok([row])).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok(saved)).mockResolvedValueOnce(ok([saved])); vi.stubGlobal("fetch", f); render(<AccountingSellerProfiles org="7" />); await draft(); const button = screen.getByRole("button", { name: "Подтвердить версию реквизитов" }); act(() => { fireEvent.click(button); fireEvent.click(button); }); expect(f).toHaveBeenCalledTimes(2); await act(async () => pending.resolve(ok([row]))); await screen.findByLabelText("Фактически сохранена версия 6"); expect(f.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
});
it("receipt shows actual server-owned name even when history refresh fails", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok(saved)).mockResolvedValueOnce(fail(503))); render(<AccountingSellerProfiles org="7" organization={{ name: "Имя до изменения", unp: seller.unp }} />); await draft(); submit(); const card = await screen.findByLabelText("Фактически сохранена версия 6"); expect(within(card).getByText(/Сохранённое сервером имя/)).toBeInTheDocument(); expect(await screen.findByRole("alert")).toHaveTextContent("История не обновлена");
});
it.each(["org", "date", "currency"])("ignores stale current response after %s change", async (kind) => {
  const pending = deferred(); const f = vi.fn().mockResolvedValueOnce(ok([row])).mockReturnValueOnce(pending.promise).mockResolvedValueOnce(ok([])); vi.stubGlobal("fetch", f); const view = render(<AccountingSellerProfiles org="7" />); await screen.findByLabelText("Историческая версия 5"); query(); if (kind === "org") view.rerender(<AccountingSellerProfiles org="8" />); else fireEvent.change(screen.getByLabelText(kind === "date" ? "Дата действующих реквизитов" : "Валюта действующих реквизитов"), { target: { value: kind === "date" ? "2026-10-01" : "USD" } }); await act(async () => pending.resolve(ok(row))); expect(screen.queryByLabelText("Действует на 2026-09-15: версия 5")).not.toBeInTheDocument();
});
it.each(["history", "POST"])("ignores late %s when org forced to change", async (kind) => {
  const pending = deferred(), f = vi.fn(); if (kind === "history") f.mockReturnValueOnce(pending.promise); else f.mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([row])).mockReturnValueOnce(pending.promise); f.mockResolvedValueOnce(ok([])); vi.stubGlobal("fetch", f); const view = render(<AccountingSellerProfiles org="7" />); if (kind === "POST") { await draft(); submit(); await waitFor(() => expect(f).toHaveBeenCalledTimes(3)); } view.rerender(<AccountingSellerProfiles org="8" />); await act(async () => pending.resolve(ok(kind === "history" ? [row] : saved))); expect(screen.queryByLabelText("Фактически сохранена версия 6")).not.toBeInTheDocument(); expect(screen.queryByLabelText("Историческая версия 5")).not.toBeInTheDocument();
});
it("invalid org and invalid form prevent requests; edits clear confirmation", async () => {
  const f = vi.fn().mockResolvedValue(ok([])); vi.stubGlobal("fetch", f); const view = render(<AccountingSellerProfiles org="" />); expect(f).not.toHaveBeenCalled(); view.rerender(<AccountingSellerProfiles org="7" />); await draft(); fireEvent.change(screen.getByLabelText("Начало действия реквизитов"), { target: { value: "" } }); expect(screen.getByLabelText("Реквизиты проверены главным бухгалтером")).not.toBeChecked(); expect(screen.getByRole("button", { name: "Подтвердить версию реквизитов" })).toBeDisabled(); expect(f).toHaveBeenCalledOnce();
});
it("native key fallback and unavailable randomness are explicit", () => {
  vi.stubGlobal("crypto", { getRandomValues: (v: Uint8Array) => v.fill(7) }); expect(sellerKey()).toBe("07".repeat(32)); vi.stubGlobal("crypto", {}); expect(() => sellerKey()).toThrow(/безопасно создать ключ/);
});
it("unavailable native randomness does not POST or leave navigation locked", async () => {
  vi.stubGlobal("crypto", {}); const f = vi.fn().mockResolvedValue(ok([row])); vi.stubGlobal("fetch", f); const busy = vi.fn(); render(<AccountingSellerProfiles org="7" onBusyChange={busy} />); await draft(); submit(); expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось безопасно создать ключ"); expect(f.mock.calls.every(([, init]) => init.method === "GET")).toBe(true); expect(busy).toHaveBeenLastCalledWith(false);
});
it("100-version page labels history limit without inventing pagination", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(Array.from({ length: 100 }, (_, i) => ({ ...row, revision: 100 - i, profile_id: 100 - i }))))); render(<AccountingSellerProfiles org="7" />); await screen.findByLabelText("Историческая версия 100"); expect(screen.getByText(/Последние 100 версий юрлица/)).toBeInTheDocument(); expect(screen.queryByRole("button", { name: /Ещё версии/ })).not.toBeInTheDocument();
});
it("new successful version obtains a different automatic key", async () => {
  const second = { ...saved, revision: 7, profile_id: 7 }; const keys = vi.fn().mockReturnValueOnce("key-a").mockReturnValueOnce("key-b"); vi.stubGlobal("crypto", { randomUUID: keys }); const f = vi.fn().mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok([row])).mockResolvedValueOnce(ok(saved)).mockResolvedValueOnce(ok([saved])).mockResolvedValueOnce(ok([saved])).mockResolvedValueOnce(ok(second)).mockResolvedValueOnce(ok([second])); vi.stubGlobal("fetch", f); render(<AccountingSellerProfiles org="7" />); await draft(); submit(); await screen.findByLabelText("Фактически сохранена версия 6"); await waitFor(() => expect(screen.getByRole("button", { name: "Обновить историю реквизитов" })).toBeEnabled()); fireEvent.click(screen.getByRole("button", { name: "Подготовить следующую версию" })); await draft(); submit(); await screen.findByLabelText("Фактически сохранена версия 7"); expect(f.mock.calls.filter(([, init]) => init.method === "POST").map(([, init]) => JSON.parse(init.body).source_key)).toEqual(["key-a", "key-b"]);
});
it.each(["foreign", "order", "duplicate", "too many"])("invalid history %s is rejected", async (kind) => {
  const rows = kind === "foreign" ? [{ ...row, organization_id: 8 }] : kind === "order" ? [row, { ...row, profile_id: 6, revision: 6 }] : kind === "duplicate" ? [row, { ...row, revision: 4 }] : Array.from({ length: 101 }, (_, i) => ({ ...row, revision: 101 - i, profile_id: 101 - i })); vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(rows))); await expect(fetchSellerHistory("7")).rejects.toThrow();
});
it.each(["currency", "future"])("invalid current %s rejected", async (kind) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...row, ...(kind === "future" ? { effective_from: "2027-01-01" } : { seller: { ...seller, currency: "USD" } }) }))); await expect(fetchSellerCurrent("7", "2026-09-15", "BYN")).rejects.toThrow();
});
it("history accepts inactive-code snapshot; request excludes client-owned actor/name/UNP", async () => {
  const f = vi.fn().mockResolvedValueOnce(ok([{ ...row, seller: { ...seller, currency: "ZZZ" } }])).mockResolvedValueOnce(ok(saved)); vi.stubGlobal("fetch", f); expect((await fetchSellerHistory("7"))[0].seller.currency).toBe("ZZZ"); await createSellerProfile("7", { ...body, actor: "forged", name: "forged", unp: "forged" } as SellerRequest); const sent = JSON.parse(f.mock.calls[1][1].body); expect(sent.actor).toBeUndefined(); expect(sent.name).toBeUndefined(); expect(sent.unp).toBeUndefined();
});
