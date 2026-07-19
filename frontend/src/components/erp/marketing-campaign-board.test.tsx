import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MarketingCampaignBoard } from "@/components/erp/marketing-campaign-board";

afterEach(() => vi.unstubAllGlobals());

describe("MarketingCampaignBoard", () => {
  it("показывает «Нет кампаний», когда backend отдаёт пустой список", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => [] })),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByText("Нет кампаний")).toBeInTheDocument();
    // заглушка растянута на все 8 колонок
    expect(screen.getByText("Нет кампаний").closest("td")).toHaveAttribute("colspan", "8");
  });

  it("показывает «Нет кампаний», когда backend недоступен (fetch кидает ошибку)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByText("Нет кампаний")).toBeInTheDocument();
  });

  it("показывает «Нет кампаний», когда backend отвечает не-ok статусом", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500, json: async () => [] })),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByText("Нет кампаний")).toBeInTheDocument();
  });

  it("рендерит строки кампаний с реальными значениями полей", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            id: 1,
            name: "Весенняя распродажа",
            channel: "Instagram",
            utm_source: "instagram",
            utm_medium: "cpc",
            utm_campaign: "spring_sale",
            leads: 42,
            budget: "1500.00",
            goal: "Рост лидов",
          },
        ],
      })),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByText("Весенняя распродажа")).toBeInTheDocument();
    expect(screen.getByText("Instagram")).toBeInTheDocument();
    expect(screen.getByText("instagram")).toBeInTheDocument();
    expect(screen.getByText("cpc")).toBeInTheDocument();
    expect(screen.getByText("spring_sale")).toBeInTheDocument();
    expect(screen.getByText("1500.00")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("Рост лидов")).toBeInTheDocument();
    expect(screen.queryByText("Нет кампаний")).not.toBeInTheDocument();
  });

  it("подставляет прочерк «—» вместо пустых UTM-полей и цели", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            id: 2,
            name: "Без атрибуции",
            channel: "Direct",
            utm_source: "",
            utm_medium: "",
            utm_campaign: "",
            leads: 0,
            budget: "0.00",
            goal: "",
          },
        ],
      })),
    );

    render(await MarketingCampaignBoard());

    // 3 UTM-поля + цель = 4 прочерка
    expect(screen.getAllByText("—")).toHaveLength(4);
    expect(screen.getByText("0")).toBeInTheDocument(); // leads=0 отрендерен как есть
  });

  it("рендерит по строке на каждую кампанию (несколько записей)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            id: 1,
            name: "Кампания A",
            channel: "VK",
            utm_source: "vk",
            utm_medium: "social",
            utm_campaign: "a",
            leads: 10,
            budget: "100.00",
            goal: "",
          },
          {
            id: 2,
            name: "Кампания B",
            channel: "Google",
            utm_source: "google",
            utm_medium: "cpc",
            utm_campaign: "b",
            leads: 20,
            budget: "200.00",
            goal: "",
          },
        ],
      })),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByText("Кампания A")).toBeInTheDocument();
    expect(screen.getByText("Кампания B")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3); // 1 заголовок + 2 данных
  });
});
