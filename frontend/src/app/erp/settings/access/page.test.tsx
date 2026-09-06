import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AccessAdminPage from "./page";

vi.mock("@/components/app-shell", () => ({ AppShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "director" }));
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: async () => ({ Authorization: "Bearer synthetic-test" }) }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: () => "oidc" }));

const response = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
afterEach(() => vi.unstubAllGlobals());

describe("CRM access page with OIDC", () => {
  it.each(["admin", "director", "commercial"])("allows server-confirmed %s with the authenticated headers", async (role) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ current_roles: [role] })).mockResolvedValueOnce(response([]));
    vi.stubGlobal("fetch", fetchMock);
    render(await AccessAdminPage());
    expect(screen.getByRole("button", { name: "Создать карточку" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/system/users/crm-staff"), expect.objectContaining({ headers: { Authorization: "Bearer synthetic-test" } }));
  });

  it.each([["sales"], ["hr"], ["sales_head"], ["onboarding", "director"], ["uma_authorization"], []])("ignores the director cookie when server roles are %j", async (...roles) => {
    const fetchMock = vi.fn().mockResolvedValue(response({ current_roles: roles }));
    vi.stubGlobal("fetch", fetchMock);
    render(await AccessAdminPage());
    expect(screen.getByRole("alert")).toHaveTextContent("нет прав");
    expect(screen.queryByRole("button", { name: "Создать карточку" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 500])("blocks management after access HTTP %i", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(response({}, status));
    vi.stubGlobal("fetch", fetchMock);
    render(await AccessAdminPage());
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось подтвердить права");
    expect(screen.queryByRole("button", { name: "Создать карточку" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([{}, { current_roles: null }, { current_roles: "not-director" }, { current_roles: ["director", null] }])("rejects malformed server roles %j without reading staff", async (body) => {
    const fetchMock = vi.fn().mockResolvedValue(response(body));
    vi.stubGlobal("fetch", fetchMock);
    render(await AccessAdminPage());
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось подтвердить права");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 500])("blocks management after staff HTTP %i", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response({ current_roles: ["director"] })).mockResolvedValueOnce(response({}, status)));
    render(await AccessAdminPage());
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Создать карточку" })).not.toBeInTheDocument();
  });
});
