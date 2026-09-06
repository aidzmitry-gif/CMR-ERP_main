import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EmployeeInvitationsPage from "./page";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "director" }));
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: async () => ({ Authorization: "Bearer synthetic-test" }) }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: () => "oidc" }));

const response = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
const reads: Record<string, unknown> = {
  access: { current_roles: ["director"] },
  departments: { departments: { Продажи: ["sales", "sales_head", "sales_cli"] } },
  invitations: [],
  "invitation-operations": [],
  "crm-staff": [],
};

function mockReads(failingPath?: string, failure?: unknown) {
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    expect(options?.headers).toEqual(expect.objectContaining({ Authorization: "Bearer synthetic-test" }));
    const path = url.split("/").at(-1)!;
    if (path === failingPath) {
      if (failure instanceof Error) throw failure;
      return failure;
    }
    return response(reads[path]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => vi.unstubAllGlobals());

describe("invitation reads", () => {
  it("lets an assigned operator prepare and read operations without activation controls", async () => {
    mockReads("access", response({ current_roles: ["crm_invitation_operator"] }));
    render(await EmployeeInvitationsPage());
    expect(screen.getByRole("button", { name: "Проверить и продолжить" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Журнал операций приглашений" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ожидают активации" })).not.toBeInTheDocument();
  });

  it("shows a truly empty successful list and keeps preflight available", async () => {
    const fetchMock = mockReads();
    render(await EmployeeInvitationsPage());
    expect(screen.getByText("Нет сотрудников, ожидающих активации.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Проверить и продолжить" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  for (const path of ["departments", "invitations", "invitation-operations"]) {
    it.each([401, 403, 500])(`distinguishes ${path} HTTP %i from an empty list`, async (status) => {
      const fetchMock = mockReads(path, response({}, status));
      render(await EmployeeInvitationsPage());
      expect(screen.getByRole("alert")).toHaveTextContent(status === 500 ? "Не удалось загрузить" : "Нет доступа");
      expect(screen.queryByText("Нет сотрудников, ожидающих активации.")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Проверить и продолжить" })).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
    });

    it(`blocks a transport failure reading ${path}`, async () => {
      mockReads(path, new Error("offline"));
      render(await EmployeeInvitationsPage());
      expect(screen.getByRole("alert")).toHaveTextContent("Проверьте соединение");
      expect(screen.queryByRole("button", { name: "Проверить и продолжить" })).not.toBeInTheDocument();
    });

    it(`rejects malformed data from ${path}`, async () => {
      mockReads(path, response(path === "departments" ? { departments: [] } : [null]));
      render(await EmployeeInvitationsPage());
      expect(screen.getByRole("alert")).toHaveTextContent("некорректные данные");
    });
  }

  it("does not read any identity lists when server roles have the wrong shape", async () => {
    const fetchMock = mockReads("access", response({ current_roles: "not-director" }));
    render(await EmployeeInvitationsPage());
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось подтвердить права");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
