import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SpravochnikhiPage from "./page";

vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "director" }));
vi.mock("@/lib/auth-headers-server", () => ({
  backendAuthHeaders: async () => ({ Authorization: "Bearer synthetic-session" }),
}));
vi.mock("@/components/erp/spravochniki/sprav-catalog", () => ({
  SpravCatalog: (props: object) => <pre data-testid="catalog">{JSON.stringify(props)}</pre>,
}));

afterEach(() => vi.unstubAllGlobals());

describe("references page OIDC SSR", () => {
  it.each([
    ["core.units", "/system/refs/units", [{ id: 1, name: "шт" }]],
    ["core.skus", "/system/mdm/sku", { result: [{ id: 2, name: "Товар" }] }],
  ])("authenticates catalog and initial rows for %s", async (key, endpoint, payload) => {
    const reference = { key, endpoint, title: "Справочник", columns: [] };
    const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => {
      if (new Headers(options?.headers).get("Authorization") !== "Bearer synthetic-session") {
        return { ok: false, status: 403 };
      }
      return { ok: true, json: async () => fetchMock.mock.calls.length === 1
        ? { departments: { Система: [reference] } } : payload };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(await SpravochnikhiPage());
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/system\/references$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(key === "core.skus"
      ? /\/system\/references\/query$/ : /\/system\/refs\/units$/);
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer synthetic-session");
    }
    if (key === "core.skus") {
      expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
      expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get("Content-Type")).toBe("application/json");
    }
    expect(screen.getByTestId("catalog")).toHaveTextContent('"initialRows":[{"id":');
    expect(screen.getByTestId("catalog")).not.toHaveTextContent("synthetic-session");
  });

  it.each([401, 403, 500])("does not load rows when catalog returns %i", async (status) => {
    const fetchMock = vi.fn(async () => ({ ok: false, status }));
    vi.stubGlobal("fetch", fetchMock);
    render(await SpravochnikhiPage());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("catalog")).toHaveTextContent('"departments":{}');
    expect(screen.getByTestId("catalog")).toHaveTextContent('"initialRows":[]');
  });
});
