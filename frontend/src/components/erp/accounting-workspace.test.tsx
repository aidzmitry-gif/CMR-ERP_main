import { render,resetCompany } from "@/test/installation-company";
import { act,fireEvent,screen } from "@testing-library/react";
import { afterEach,beforeEach as configureBeforeEach,expect,it,vi } from "vitest";
import { AccountingView } from "./accounting-view";
vi.mock("@/lib/instance-organization", async () => { const fixture = await import("@/test/installation-company"); return { fetchInstanceOrganization: fixture.fetchTestInstanceOrganization }; });

afterEach(() => vi.unstubAllGlobals());
it("keeps the book mounted while confirmation is pending and refreshes the workspace afterwards", async () => {
  let finish!: () => void;
  let committed = false;
  const delayed = new Promise<void>((resolve) => { finish = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
    if (options?.method === "POST") { await delayed; committed = true; }
    const data = url.endsWith("/organizations") ? [{ id: 1, name: "Test", unp: "999999999" }]
      : url.includes("/reports?") ? { pending_documents: committed ? 0 : 1 }
      : url.endsWith("/inbox") ? committed ? [] : [{ id: 1, event_key: "Pending source", month: "2026-09", payload: {} }]
      : url.endsWith("/catalog") ? { accounts: [] } : [];
    return { ok: true, json: async () => data };
  }));
  render(<AccountingView />);
  await screen.findByText(/включительно: 1\./);
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Документы и ошибки проведения" }));
  fireEvent.click(await screen.findByText("Pending source · 2026-09"));
  fireEvent.click(screen.getByText("Подтвердить пакет и повторить проведение"));
  expect(screen.getByRole("button", { name: "Рабочее место", exact: true })).toBeDisabled();
  expect(screen.queryByRole("combobox", { name: "Организация", exact: true })).not.toBeInTheDocument();
  await act(async () => { finish(); await delayed; });
  await screen.findByText("Документ проверен и проведён.");
  fireEvent.click(screen.getByRole("button", { name: "Рабочее место", exact: true }));
  await screen.findByText(/включительно: 0\./);
});

configureBeforeEach(() => resetCompany(1));
