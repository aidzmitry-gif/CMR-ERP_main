import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  router: { push: vi.fn(), refresh: vi.fn() },
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  useSearchParams: () => navigation.params,
}));

import LoginPage from "@/app/login/page";

const employee = {
  username: "alice",
  full_name: "Алиса Менеджер",
  role: "sales",
  role_title: "Продажи",
};

function response(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response;
}

beforeEach(() => {
  vi.clearAllMocks();
  process.env.NEXT_PUBLIC_AUTH_MODE = "dev";
  delete process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER;
  delete process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID;
  delete process.env.NEXT_PUBLIC_APP_ORIGIN;
  navigation.params = new URLSearchParams();
  global.fetch = vi.fn().mockResolvedValue(response({ users: [employee] })) as unknown as typeof fetch;
});

describe("LoginPage", () => {
  it("загружает сотрудников и отправляет dev-вход на маршрут роли", async () => {
    render(<LoginPage />);
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("alice"));

    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ username: "alice" }) }),
    ));
    expect(navigation.router.push).toHaveBeenCalledWith("/crm/deals");
    expect(navigation.router.refresh).toHaveBeenCalledOnce();
  });

  it("показывает ошибку при отказе backend и при сетевой ошибке входа", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(response({ users: [employee] }))
      .mockResolvedValueOnce(response({}, false)) as unknown as typeof fetch;
    render(<LoginPage />);
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("alice"));
    fireEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(screen.getByText("Не удалось войти. Попробуйте ещё раз.")).toBeInTheDocument());

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(response({ users: [employee] }))
      .mockRejectedValueOnce(new Error("offline")) as unknown as typeof fetch;
    render(<LoginPage />);
    await waitFor(() => expect(screen.getAllByRole("combobox")[1]).toHaveValue("alice"));
    fireEvent.click(screen.getAllByRole("button", { name: "Войти" })[1]);
    await waitFor(() => expect(screen.getByText("Сеть недоступна.")).toBeInTheDocument());
  });

  it("сообщает о недоступности списка сотрудников при ошибке загрузки", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("backend down")) as unknown as typeof fetch;
    render(<LoginPage />);
    await waitFor(() =>
      expect(screen.getByText("Не удалось загрузить список сотрудников (backend недоступен).")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Войти" })).toBeDisabled();
  });

  it("в режиме OIDC показывает ошибку callback и понятное сообщение о конфигурации", async () => {
    process.env.NEXT_PUBLIC_AUTH_MODE = "oidc";
    navigation.params = new URLSearchParams("error=access_denied");
    render(<LoginPage />);

    expect(screen.getByText("Вход через Keycloak")).toBeInTheDocument();
    expect(screen.getByText("access_denied")).toBeInTheDocument();
    expect(screen.getByText(/Keycloak не настроен/)).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
