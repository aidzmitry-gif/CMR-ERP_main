import { act,render,screen,waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach,expect,it,vi } from "vitest";
import { ProcurementKanban } from "./erp/procurement-kanban";
import { InstanceOrganizationGate,useInstanceOrganization,withInstanceOrganization } from "./instance-organization-gate";

const context = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Configured installation", unp: "987654321" } };
const response = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body, text: async () => JSON.stringify(body) });
afterEach(() => vi.unstubAllGlobals());

it("opens procurement automatically for the configured company without listing or selecting companies", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url === "/api/system/instance-organization") return response(context);
    if (url.endsWith("request-plan-context")) return response({ organization_id: 7, principal: "fixture", can_manage: false });
    if (url.includes("owned-sources")) return response({ organization_id: 7, items: [], next_after_id: null });
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementKanban />);
  expect(await screen.findByLabelText("Канбан закупок")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => url.includes("/organizations/7/"))).toBe(true);
  expect(fetcher.mock.calls.some(([url]) => /receipt-organizations|organizations\/8/.test(url))).toBe(false);
});

it("rejects a link to another company before loading its procurement documents", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(context));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementKanban suggestedOrg="8" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("не совпадает");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it.each([401, 403, 409, 503])("does not load or write module data for refused installation context %s", async status => {
  const fetcher = vi.fn().mockResolvedValue(response({}, status));
  vi.stubGlobal("fetch", fetcher);
  render(<ProcurementKanban />);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link", { name: "Настройки организации" })).toHaveAttribute("href", "/erp/settings");
  expect(screen.queryByLabelText("Канбан закупок")).not.toBeInTheDocument();
});

it("reuses the same verified context in nested screens without choosing or fetching another company", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(context));
  vi.stubGlobal("fetch", fetcher);
  function Child() { return <p>Company ID {useInstanceOrganization().id}</p>; }
  render(<InstanceOrganizationGate>{() => <InstanceOrganizationGate>{() => <Child />}</InstanceOrganizationGate>}</InstanceOrganizationGate>);
  expect(await screen.findByText("Company ID 7")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("does not mount a scoped API consumer until the installation context is verified", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn((url: string) => url === "/api/system/instance-organization"
    ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(response({})));
  vi.stubGlobal("fetch", fetcher);
  function Consumer() {
    const org = useInstanceOrganization();
    useEffect(() => { void fetch(`/api/procurement/organizations/${org.id}/requests`); }, [org.id]);
    return <p>Scoped consumer</p>;
  }
  const Scoped = withInstanceOrganization(Consumer);
  render(<Scoped />);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("Scoped consumer")).not.toBeInTheDocument();
  await act(async () => finish(response(context)));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  expect(fetcher.mock.calls[1][0]).toBe("/api/procurement/organizations/7/requests");
});
