import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  mode: "oidc" as "dev" | "oidc",
  error: null as string | null,
  config: {
    issuer: "https://keycloak.example/realms/test",
    clientId: "test-client",
    redirectUri: "",
  } as { issuer: string; clientId: string; redirectUri: string } | null,
  push: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: auth.push, refresh: auth.refresh }),
  useSearchParams: () => ({
    get: (name: string) => (name === "error" ? auth.error : null),
  }),
}));

vi.mock("@/lib/auth-mode", () => ({
  frontendAuthMode: () => auth.mode,
  keycloakPublicConfig: () => auth.config,
}));

import LoginPage from "./page";

type VirtualConsoleLike = {
  on: (event: "jsdomError", listener: (error: Error) => void) => void;
  removeListener: (event: "jsdomError", listener: (error: Error) => void) => void;
};

const cleanupNavigationWatchers: Array<() => void> = [];

function watchNavigationAttempts() {
  const errors: Error[] = [];
  const listener = (error: Error) => errors.push(error);
  // jsdom's Location.href setter is unforgeable, so observe its navigation error instead.
  const virtualConsole = (window as unknown as { _virtualConsole: VirtualConsoleLike })._virtualConsole;
  virtualConsole.on("jsdomError", listener);
  cleanupNavigationWatchers.push(() => virtualConsole.removeListener("jsdomError", listener));
  return errors;
}

function navigationAttempts(errors: Error[]) {
  return errors.filter((error) => error.message.includes("Not implemented: navigation"));
}

describe("LoginPage", () => {
  beforeEach(() => {
    auth.mode = "oidc";
    auth.error = null;
    auth.config = {
      issuer: "https://keycloak.example/realms/test",
      clientId: "test-client",
      redirectUri: "",
    };
    auth.push.mockReset();
    auth.refresh.mockReset();
  });

  afterEach(() => {
    cleanupNavigationWatchers.splice(0).forEach((cleanup) => cleanup());
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps a session-expired OIDC error visible and allows a manual retry", async () => {
    auth.error = "session_expired";
    const navigationErrors = watchNavigationAttempts();

    render(<LoginPage />);

    expect(screen.getByText("Сессия завершилась. Войдите снова.")).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Войти" });
    expect(retry).toBeInTheDocument();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(navigationAttempts(navigationErrors)).toHaveLength(0);

    fireEvent.click(retry);
    await waitFor(() => expect(navigationAttempts(navigationErrors)).toHaveLength(1));
  });

  it("automatically starts OIDC when there is no error", async () => {
    const navigationErrors = watchNavigationAttempts();

    render(<LoginPage />);

    await waitFor(() => expect(navigationAttempts(navigationErrors)).toHaveLength(1));
  });

  it("preserves the dev login flow", async () => {
    auth.mode = "dev";
    auth.config = null;
    const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
      if (input === "/api/system/users") {
        return {
          ok: true,
          json: async () => ({
            users: [{ username: "alice", full_name: "Alice", role: "director", role_title: "Руководитель" }],
          }),
        } as Response;
      }
      if (input === "/api/auth/login") {
        return { ok: true, json: async () => ({ user: { role: "director" } }) } as Response;
      }
      throw new Error(`Unexpected fetch: ${input} ${JSON.stringify(init)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LoginPage />);

    expect(await screen.findByRole("option", { name: "Alice — Руководитель" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(auth.push).toHaveBeenCalled();
    expect(auth.refresh).toHaveBeenCalled();
  });
});
