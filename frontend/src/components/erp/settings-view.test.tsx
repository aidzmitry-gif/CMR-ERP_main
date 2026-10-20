import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsView } from "@/components/erp/settings-view";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("SettingsView", () => {
  it("shows the server-configured company without another company picker", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("instance-organization")
      ? { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Synthetic organization", unp: "987654321" } }
      : { loaded_modules: [], routers: [], events: [], permissions: [], widgets: [] } })));
    render(<SettingsView />);
    expect(await screen.findByText("Synthetic organization · УНП 987654321")).toBeInTheDocument();
    expect(screen.getByText(/Изменение настройки выполняет администратор сервера/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows unavailable company configuration instead of inventing an organization", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: !url.includes("instance-organization"), status: 503,
      json: async () => ({ loaded_modules: [], routers: [], events: [], permissions: [], widgets: [] }) })));
    render(<SettingsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Юрлицо установки не настроено/);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("показывает реестр модулей, роуты, события и права", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          loaded_modules: ["sales", "integrations"],
          routers: [{ module: "sales", prefix: "/sales" }],
          events: [{ module: "finance", event_type: "finance.payment.paid" }],
          permissions: ["sales.deal.read"],
          widgets: [],
        }),
      }),
    );
    render(<SettingsView />);
    expect(await screen.findByText(/Подключённые модули/)).toBeInTheDocument();
    expect(screen.getAllByText("sales").length).toBeGreaterThan(0);
    expect(screen.getByText("integrations")).toBeInTheDocument();
    expect(screen.getByText("sales.deal.read")).toBeInTheDocument();
    expect(screen.getByText(/finance\.payment\.paid/)).toBeInTheDocument();
  });

  it("показывает загрузку при ошибке запроса", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<SettingsView />);
    expect(await screen.findByText("Загрузка…")).toBeInTheDocument();
  });

  it("links the registered accounting module to the accountant workspace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        loaded_modules: ["sales", "accounting"],
        routers: [],
        events: [],
        permissions: [],
        widgets: [],
      }),
    }));

    render(<SettingsView />);

    const link = await screen.findByRole("link", { name: "Открыть Бухгалтерия" });
    expect(link).toHaveAttribute("href", "/erp/accounting");
    expect(link).toHaveTextContent("Бухгалтерия · accounting");
    expect(screen.getByText("sales")).toBeInTheDocument();
  });
});
