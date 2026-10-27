import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingView } from "./accounting-view";

afterEach(() => vi.unstubAllGlobals());
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
const seller = { name: "SERVER BOOK", unp: "999999999", currency: "BYN", address: "ADDR", account: "ACC", bank: "BANK", bik: "BIK", director: "DIRECTOR", phone: "", email: "", logo_data_url: "", stamp_data_url: null, signature_data_url: null };
const receipt = { organization_id: 7, profile_id: 1, revision: 1, effective_from: "2026-09-10", digest: "a".repeat(64), seller, evidence: "EVIDENCE", actor: "chief" };
function api(post: () => Promise<unknown>) { return vi.fn((url: string, init?: RequestInit) => {
  if (init?.method === "POST") return post();
  if (url === "/api/accounting/organizations") return Promise.resolve(ok([{ id: 7, name: "A", unp: "111111111" }, { id: 8, name: "B", unp: "222222222" }]));
  if (url.includes("/reports?")) return Promise.resolve(ok({ pending_documents: 0 }));
  return Promise.resolve(ok([]));
}); }
async function open() {
  render(<AccountingView />); await screen.findByText(/включительно: 0\./); fireEvent.click(screen.getByRole("button", { name: "Закрытие месяца" })); fireEvent.click(screen.getByRole("button", { name: "Реквизиты продавца" }));
  await screen.findByText("Подтверждённых версий реквизитов пока нет."); fireEvent.click(screen.getByRole("button", { name: "Подготовить новую версию реквизитов" }));
  for (const [label, value] of [["Начало действия реквизитов", "2026-09-10"], ["Валюта новой версии", "BYN"], ["Адрес продавца", "ADDR"], ["Расчётный счёт", "ACC"], ["Банк продавца", "BANK"], ["БИК", "BIK"], ["Руководитель", "DIRECTOR"], ["Основание реквизитов", "EVIDENCE"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByLabelText("Реквизиты проверены главным бухгалтером"));
}
it("home integration freezes organization, dates and tabs through unknown response then unlocks after receipt", async () => {
  let resolve!: (v: unknown) => void; const pending = new Promise((r) => { resolve = r; }); let count = 0; const f = api(() => ++count === 1 ? pending : Promise.resolve(ok(receipt))); vi.stubGlobal("fetch", f); await open(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить версию реквизитов" }));
  expect(screen.getByLabelText("Организация")).toBeDisabled(); expect(screen.getByLabelText("Начало периода")).toBeDisabled(); expect(screen.getByRole("button", { name: "Банк и платежи" })).toBeDisabled(); expect(screen.getByRole("button", { name: "Рабочее место" })).toBeDisabled();
  await act(async () => resolve({ ok: false, status: 503 })); await screen.findByRole("button", { name: "Повторить сохранённый запрос" }); expect(screen.getByLabelText("Организация")).toBeDisabled(); fireEvent.click(screen.getByRole("button", { name: "Повторить сохранённый запрос" })); await screen.findByLabelText("Фактически сохранена версия 1"); expect(screen.getByLabelText("Организация")).toBeEnabled();
  const posts = f.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(2); expect(posts[0][1]?.body).toBe(posts[1][1]?.body);
  fireEvent.change(screen.getByLabelText("Организация"), { target: { value: "8" } }); expect(screen.queryByLabelText("Фактически сохранена версия 1")).not.toBeInTheDocument(); expect(screen.getByLabelText("Дата действующих реквизитов")).toHaveValue("");
});
it("first explicit chief denial releases existing workspace navigation", async () => {
  vi.stubGlobal("fetch", api(async () => ({ ok: false, status: 403 }))); await open(); fireEvent.click(screen.getByRole("button", { name: "Подтвердить версию реквизитов" })); expect(await screen.findByRole("alert")).toHaveTextContent("403:"); expect(screen.getByLabelText("Организация")).toBeEnabled(); expect(screen.getByRole("button", { name: "Рабочее место" })).toBeEnabled(); expect(screen.queryByText(/сохранена сервером/)).not.toBeInTheDocument();
});
