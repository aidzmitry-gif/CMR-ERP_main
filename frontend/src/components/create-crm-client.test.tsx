import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CreateCrmClient } from "./create-crm-client";

afterEach(() => vi.unstubAllGlobals());
const owners = { ok: true, json: async () => [{ id: 491, name: "Owner" }] };

it("retains the request key after a lost reply and reports the confirmed client", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(owners)
    .mockRejectedValueOnce(new Error("Ответ потерян"))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 7, name: "Client", source: "crm" }) });
  vi.stubGlobal("fetch", fetch);
  const created = vi.fn();
  render(<CreateCrmClient onCreated={created} onCancel={vi.fn()} />);
  await waitFor(() => expect(screen.getByLabelText("Ответственный")).toHaveValue("491"));
  fireEvent.change(screen.getByLabelText("Название клиента"), { target: { value: "Client" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать клиента" }));
  await screen.findByText("Ответ потерян");
  expect(created).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Создать клиента" }));
  await waitFor(() => expect(created).toHaveBeenCalledWith("Client"));
  expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[2][1].body);
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ owner_id: 491, unp: null });
});

it("keeps an owner-load error distinct from no employees and retries", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: false, status: 500 }).mockResolvedValueOnce(owners));
  render(<CreateCrmClient onCreated={vi.fn()} onCancel={vi.fn()} />);
  await screen.findByText("Не удалось загрузить сотрудников.");
  expect(screen.queryByText("Нет активного сотрудника CRM для назначения владельцем.")).toBeNull();
  expect(screen.getByRole("button", { name: "Создать клиента" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку сотрудников" }));
  await waitFor(() => expect(screen.getByLabelText("Ответственный")).toHaveValue("491"));
});

it("does not deliver a late creation result after leaving the form", async () => {
  let finish!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(owners).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; })));
  const created = vi.fn();
  const view = render(<CreateCrmClient onCreated={created} onCancel={vi.fn()} />);
  await waitFor(() => expect(screen.getByLabelText("Ответственный")).toHaveValue("491"));
  fireEvent.change(screen.getByLabelText("Название клиента"), { target: { value: "Client" } });
  fireEvent.click(screen.getByRole("button", { name: "Создать клиента" }));
  view.unmount();
  await act(async () => { finish({ ok: true, json: async () => ({ id: 7, name: "Client", source: "crm" }) }); });
  expect(created).not.toHaveBeenCalled();
});
