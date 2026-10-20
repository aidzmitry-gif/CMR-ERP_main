import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { InstanceOrganizationGate } from "./instance-organization-gate";

afterEach(() => vi.unstubAllGlobals());
const context = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Synthetic company", unp: "987654321" } };
const response = (value: unknown, status = 200) => ({ ok: status === 200, status, json: async () => value });

it("does not mount or query a scoped screen before context arrives", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  const child = vi.fn(() => <p>Scoped screen</p>);
  render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  expect(screen.getByRole("status")).toHaveTextContent("Загрузка юрлица");
  expect(child).not.toHaveBeenCalled();
});

it("passes only the server-confirmed company and has no company picker", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(context)));
  const child = vi.fn(org => <p>Scoped {org.id}</p>);
  render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  expect(await screen.findByText("Scoped 7")).toBeInTheDocument();
  expect(screen.getByText("Synthetic company · УНП 987654321")).toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(child).toHaveBeenCalledWith(context.organization);
});

it("recovers configuration before mounting children after retry", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response({}, 503)).mockResolvedValue(response(context));
  vi.stubGlobal("fetch", fetcher);
  const child = vi.fn(() => <p>Scoped screen</p>);
  render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  expect(await screen.findByRole("alert")).toHaveTextContent("не настроено");
  expect(child).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Настройки организации" })).toHaveAttribute("href", "/erp/settings");
  await userEvent.click(screen.getByRole("button", { name: "Повторить загрузку юрлица" }));
  expect(await screen.findByText("Scoped screen")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("ignores a late context response after the screen is unmounted", async () => {
  let finish!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise(resolve => { finish = resolve; })));
  const child = vi.fn(() => <p>Scoped screen</p>);
  const view = render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  view.unmount();
  await act(async () => { finish(response(context)); });
  expect(child).not.toHaveBeenCalled();
});

it("does not mount data for a malformed context", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...context, organization: { ...context.organization, id: -1 } })));
  const child = vi.fn(() => <p>Scoped screen</p>);
  render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  expect(await screen.findByRole("alert")).toHaveTextContent("некорректное");
  expect(child).not.toHaveBeenCalled();
});

it("requires ordinary login on an expired session without loading children", async () => {
  const fetcher = vi.fn().mockResolvedValue(response({}, 401));
  vi.stubGlobal("fetch", fetcher);
  const child = vi.fn(() => <p>Scoped screen</p>);
  render(<InstanceOrganizationGate>{child}</InstanceOrganizationGate>);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Войдите в систему"));
  expect(child).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});
