import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ fetchAccess: vi.fn(), currentRole: vi.fn() }));

vi.mock("@/components/sidebar", () => ({
  Sidebar: ({ allowedSlugs, roleTitle, accessUnavailable }: { allowedSlugs: string[] | null; roleTitle: string; accessUnavailable?: boolean }) => (
    <div data-testid="sidebar" data-allowed={JSON.stringify(allowedSlugs)} data-role-title={roleTitle} data-access-unavailable={String(accessUnavailable)} />
  ),
}));
vi.mock("@/components/topbar", () => ({
  Topbar: ({ crumbs }: { crumbs: string[] }) => <div data-testid="topbar">{crumbs.join("/")}</div>,
}));
vi.mock("@/components/calls/active-call-provider", () => ({
  ActiveCallProvider: ({ children, enabled }: { children: ReactNode; enabled?: boolean }) => (
    <div data-testid="call-stream" data-enabled={String(enabled)}>{children}</div>
  ),
}));
// серверные зависимости AppShell: dev-сессия (логин/роль), редирект-гейт и матрица доступа
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/role-server", () => ({
  currentUserName: async () => "Харькович Д.С.",
  currentRole: mocks.currentRole,
}));
vi.mock("@/lib/access", () => ({ fetchAccess: mocks.fetchAccess }));
// backendAuthHeaders зовёт cookies() (next/headers) — в vitest нет request store → мокаем шлюз
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: async () => ({}) }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: () => "oidc" }));

import { AppShell } from "@/components/app-shell";

const backendRoleSlugs = ["sales", "sales_head", "sales_manager", "sales_cli", "hr", "admin", "director", "commercial", "Гость"];

function validMatrix(overrides: Record<string, unknown> = {}) {
  return {
    ...Object.fromEntries(backendRoleSlugs.map((slug) => [slug, ["crm"]])),
    ...overrides,
  };
}

function accessFor(currentRoles: unknown, matrix: unknown = validMatrix()) {
  return {
    current_roles: currentRoles,
    roles: backendRoleSlugs.map((slug) => ({ slug, title: slug })),
    matrix,
  };
}

async function renderCallGate(access: unknown, cookieRole = "sales") {
  cleanup();
  mocks.currentRole.mockResolvedValue(cookieRole);
  mocks.fetchAccess.mockResolvedValue(access);
  const ui = await AppShell({ crumbs: ["CRM"], children: <div>содержимое страницы</div> });
  render(ui);
  return screen.getByTestId("call-stream");
}

beforeEach(() => {
  mocks.currentRole.mockResolvedValue("sales");
  mocks.fetchAccess.mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AppShell", () => {
  it.each([
    ["unavailable response", null, true, [], false],
    ["unverified roles", accessFor([]), true, [], false],
    ["malformed role matrix", accessFor(["sales"], validMatrix({ sales: ["crm", 3] })), true, [], false],
    ["verified empty modules", accessFor(["sales"], validMatrix({ sales: [] })), false, [], false],
    ["verified CRM modules", accessFor(["sales"]), false, ["crm"], true],
  ])("distinguishes navigation state: %s", async (_name, access, unavailable, allowed, callsEnabled) => {
    const gate = await renderCallGate(access);
    expect(screen.getByTestId("sidebar")).toHaveAttribute("data-access-unavailable", String(unavailable));
    expect(screen.getByTestId("sidebar")).toHaveAttribute("data-allowed", JSON.stringify(allowed));
    expect(gate).toHaveAttribute("data-enabled", String(callsEnabled));
  });

  it("рендерит сайдбар, топбар с крошками и контент (вошедший пользователь)", async () => {
    // AppShell — async server component: вызываем как функцию и рендерим результат
    const ui = await AppShell({ crumbs: ["CRM", "Лиды"], children: <div>содержимое страницы</div> });
    render(ui);
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveTextContent("CRM/Лиды");
    expect(screen.getByText("содержимое страницы")).toBeInTheDocument();
  });

  it("SHELL-ADMIN blocks the call stream", async () => {
    const gate = await renderCallGate(accessFor(["admin"]));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-DIRECTOR blocks the call stream", async () => {
    const gate = await renderCallGate(accessFor(["director"]));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-COMMERCIAL blocks the call stream", async () => {
    const gate = await renderCallGate(accessFor(["commercial"]));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-MIXED-SUPER blocks any superrole or guest mixed with sales", async () => {
    for (const role of ["admin", "director", "commercial", "Гость"]) {
      const gate = await renderCallGate(accessFor(["sales", role]));
      expect(gate).toHaveAttribute("data-enabled", "false");
    }
  });

  it("SHELL-HR-STALE-COOKIE uses the CRM matrix, not a stale director cookie", async () => {
    const gate = await renderCallGate(accessFor(["hr"]), "director");
    expect(gate).toHaveAttribute("data-enabled", "true");
  });

  it("SHELL-SALES-UNKNOWN keeps a known CRM role when another role string is unknown", async () => {
    const gate = await renderCallGate(accessFor(["sales", "future_role"]), "director");
    expect(gate).toHaveAttribute("data-enabled", "true");
  });

  it("SHELL-NO-CRM denies a known role without CRM in its matrix", async () => {
    const gate = await renderCallGate(accessFor(["sales"], validMatrix({ sales: ["leads"] })));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-NULL-ACCESS ignores a sales cookie when backend access is unavailable", async () => {
    const gate = await renderCallGate(null, "sales");
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-EMPTY-ROLES denies an empty backend role list", async () => {
    const gate = await renderCallGate(accessFor([]));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-ROLES-STRING denies a non-array backend role value", async () => {
    const gate = await renderCallGate(accessFor("sales"));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-NONSTRING-ROLE denies a role list containing a non-string value", async () => {
    const gate = await renderCallGate(accessFor(["sales", 42]));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-UNKNOWN-ONLY denies a role without a backend matrix entry", async () => {
    const gate = await renderCallGate(accessFor(["future_role"], {}));
    expect(gate).toHaveAttribute("data-enabled", "false");
  });

  it("SHELL-MALFORMED-MATRIX safely denies null and non-array matrices", async () => {
    for (const matrix of [null, { sales: "crm" }]) {
      const gate = await renderCallGate(accessFor(["sales"], matrix));
      expect(gate).toHaveAttribute("data-enabled", "false");
      expect(screen.getByTestId("sidebar")).toHaveAttribute("data-allowed", "[]");
    }
  });

  it("SHELL-METADATA-INDEPENDENT enables a valid HR matrix with missing role labels", async () => {
    const withNullMetadata = { ...accessFor(["hr"]), roles: null };
    const withoutMetadata = { current_roles: ["hr"], matrix: validMatrix() };
    for (const access of [withNullMetadata, withoutMetadata]) {
      const gate = await renderCallGate(access, "director");
      expect(gate).toHaveAttribute("data-enabled", "true");
      expect(screen.getByTestId("sidebar")).toHaveAttribute("data-role-title", "hr");
    }
  });
});
