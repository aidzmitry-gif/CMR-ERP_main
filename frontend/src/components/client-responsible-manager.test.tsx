import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ClientResponsibleManager } from "./client-responsible-manager";

afterEach(() => vi.unstubAllGlobals());
const initial = { client_id: 11, source: "mdm", revision: 3, responsible_manager: null, can_edit: true };

it("saves a selected real employee with the observed revision", async () => {
  const fetchMock = vi.fn().mockImplementation((_url: string, options?: RequestInit) => Promise.resolve(Response.json(options?.method === "PUT"
    ? { ...initial, revision: 4, responsible_manager: { employee_id: 19, name: "Артём", active: true } }
    : _url.endsWith('/owners') ? [{ id: 19, name: "Артём" }] : initial)));
  vi.stubGlobal("fetch", fetchMock);
  render(<ClientResponsibleManager clientId={11} />);
  expect(await screen.findByText("Не назначен")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Назначить менеджера" }));
  await screen.findByRole("option", { name: "Артём" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить менеджера" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/sales/counterparties/11/responsible', expect.objectContaining({
    method: "PUT", body: JSON.stringify({ employee_id: 19, expected_revision: 3 }),
  })));
  expect(await screen.findByRole("button", { name: "Изменить менеджера" })).toBeInTheDocument();
  expect(screen.getByText("Артём")).toBeInTheDocument();
});

it("keeps a revision conflict visible and offers readback instead of automatic retry", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => Promise.resolve(options?.method === "PUT"
    ? new Response(null, { status: 409 }) : Response.json(url.endsWith('/owners') ? [{ id: 19, name: "Артём" }] : initial)));
  vi.stubGlobal("fetch", fetchMock);
  render(<ClientResponsibleManager clientId={11} />);
  fireEvent.click(await screen.findByRole("button", { name: "Назначить менеджера" }));
  await screen.findByRole("option", { name: "Артём" });
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "19" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить менеджера" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Карточка клиента изменилась");
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'PUT')).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Обновить назначение" })).toBeInTheDocument();
});
