import { fireEvent,render,screen,waitFor } from "@testing-library/react";
import { afterEach,expect,it,vi } from "vitest";
import { InstallationOrganizationSettings } from "./installation-organization-settings";

const own = { id: 7, name: "Synthetic seller A", unp: "987654321" };
const other = { id: 8, name: "Synthetic seller B", unp: "123456789" };
const state = { organization: null, revision: 0, configuration: null, can_manage: true, organizations: [own, other] };
const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function choose() {
  fireEvent.change(await screen.findByLabelText("Юрлицо для всей платформы"), { target: { value: "7" } });
}
const save = () => fireEvent.click(screen.getByRole("button", { name: "Сохранить для всей платформы" }));

it("does not choose a company automatically and saves the explicit platform seller", async () => {
  const request = vi.fn().mockResolvedValueOnce(ok(state)).mockResolvedValueOnce(ok({ organization: own, revision: 1, configuration: "platform_settings" }));
  vi.stubGlobal("fetch", request);
  render(<InstallationOrganizationSettings />);
  expect(await screen.findByLabelText("Юрлицо для всей платформы")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Сохранить для всей платформы" })).toBeDisabled();
  await choose(); save();
  expect(await screen.findByRole("status")).toHaveTextContent("Сохранено для всей платформы: Synthetic seller A");
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ organization_id: 7, expected_revision: 0, request_id: expect.any(String) });
  expect(request.mock.calls[1][1].method).toBe("PUT");
  expect(screen.getByText(/Ранее оформленные документы сохраняют своё юрлицо/)).toBeInTheDocument();
});

it("keeps ordinary users read-only and never presents an organization picker", async () => {
  const request = vi.fn().mockResolvedValue(ok({ ...state, organization: own, can_manage: false, organizations: [] }));
  vi.stubGlobal("fetch", request); render(<InstallationOrganizationSettings />);
  await screen.findByText(/Изменение доступно администратору/);
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Сохранить/ })).not.toBeInTheDocument();
  expect(request).toHaveBeenCalledOnce();
});

it.each(["network", "503"])("retains the exact command after an unknown %s result", async failure => {
  const request = vi.fn().mockResolvedValueOnce(ok(state));
  if (failure === "network") request.mockRejectedValueOnce(new Error("lost"));
  else request.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: "Unavailable" }) });
  request.mockResolvedValueOnce(ok({ organization: own, revision: 1, configuration: "platform_settings" }));
  vi.stubGlobal("fetch", request); render(<InstallationOrganizationSettings />);
  await choose(); save();
  fireEvent.click(await screen.findByRole("button", { name: "Повторить тот же запрос" }));
  expect(screen.getByLabelText("Юрлицо для всей платформы")).toBeDisabled();
  await screen.findByText(/Сохранено для всей платформы/);
  expect(request.mock.calls[2][1].body).toBe(request.mock.calls[1][1].body);
});

it("requires rereading a stale setting instead of overwriting another administrator", async () => {
  const request = vi.fn().mockResolvedValueOnce(ok(state))
    .mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: "Настройку уже изменили" }) })
    .mockResolvedValueOnce(ok({ ...state, organization: other, revision: 1, configuration: "platform_settings" }));
  vi.stubGlobal("fetch", request); render(<InstallationOrganizationSettings />);
  await choose(); save();
  fireEvent.click(await screen.findByRole("button", { name: "Перечитать настройку" }));
  await waitFor(() => expect(screen.getByLabelText("Юрлицо для всей платформы")).toHaveValue("8"));
  expect(request.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
});

it("does not claim success for a receipt from another company", async () => {
  const request = vi.fn().mockResolvedValueOnce(ok(state)).mockResolvedValueOnce(ok({ organization: other, revision: 1, configuration: "platform_settings" }));
  vi.stubGlobal("fetch", request); render(<InstallationOrganizationSettings />);
  await choose(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent("не подтверждено сервером");
  expect(screen.getByRole("button", { name: "Повторить тот же запрос" })).toBeEnabled();
  expect(screen.getByLabelText("Юрлицо для всей платформы")).toBeDisabled();
  expect(screen.queryByText(/Сохранено для всей платформы/)).not.toBeInTheDocument();
});

it("unlocks a known permission refusal without reporting a saved setting", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok(state)).mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({ detail: "No permission" }) }));
  render(<InstallationOrganizationSettings />); await choose(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent("No permission");
  expect(screen.getByLabelText("Юрлицо для всей платформы")).toBeEnabled();
});

it.each([null, { ...state, organizations: [own, own] }, { ...state, revision: -1 }])("refuses malformed settings %j", async data => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(data))); render(<InstallationOrganizationSettings />);
  expect(await screen.findByRole("alert")).toHaveTextContent("проверить настройку");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});

it("broadcasts a confirmed setting change and never overwrites a configured identity on load", async () => {
  const notified = vi.fn(); window.addEventListener("erp-installation-organization-changed", notified);
  try {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(ok({ ...state, organization: own, revision: 2, configuration: "platform_settings" }))
      .mockResolvedValueOnce(ok({ organization: other, revision: 3, configuration: "platform_settings" })));
    render(<InstallationOrganizationSettings />);
    expect(await screen.findByLabelText("Юрлицо для всей платформы")).toHaveValue("7");
    expect(screen.getByRole("button", { name: "Сохранить для всей платформы" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Юрлицо для всей платформы"), { target: { value: "8" } }); save();
    await screen.findByText(/Сохранено для всей платформы/); expect(notified).toHaveBeenCalledOnce();
  } finally { window.removeEventListener("erp-installation-organization-changed", notified); }
});
