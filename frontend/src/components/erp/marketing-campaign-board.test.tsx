import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authHeaders = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: authHeaders }));

import { MarketingCampaignBoard } from "@/components/erp/marketing-campaign-board";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => {
  authHeaders.mockReset().mockResolvedValue({ "X-Test-Principal": "current-ssr-user" });
});

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

  it("отличает сетевую ошибку от подтверждённого пустого списка", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить UTM-атрибуцию");
    expect(screen.queryByText("Нет кампаний")).not.toBeInTheDocument();
  });

  it("отличает HTTP 500 от подтверждённого пустого списка", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500, json: async () => [] })),
    );

    render(await MarketingCampaignBoard());

    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить UTM-атрибуцию");
    expect(screen.queryByText("Нет кампаний")).not.toBeInTheDocument();
  });

  it("передаёт текущую серверную сессию без переопределения роли и без кеширования", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", fetcher);
    render(await MarketingCampaignBoard());
    expect(authHeaders).toHaveBeenCalledExactlyOnceWith();
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(
      `${process.env.BACKEND_URL ?? "http://127.0.0.1:8000"}/marketing/campaigns/attribution`,
      { cache: "no-store", headers: { "X-Test-Principal": "current-ssr-user" } },
    );
  });

  it.each([401, 403])("показывает отказ доступа HTTP %s без тела ответа", async (status) => {
    const body = vi.fn(async () => ({ detail: "private backend detail" }));
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status, json: body })));
    render(await MarketingCampaignBoard());
    expect(screen.getByRole("alert")).toHaveTextContent("Нет доступа к UTM-атрибуции");
    expect(screen.queryByText("Нет кампаний")).not.toBeInTheDocument();
    expect(screen.queryByText(/private backend detail/)).not.toBeInTheDocument();
    expect(body).not.toHaveBeenCalled();
  });

  it("не выдаёт повреждённый ответ за кампании или пустой список", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [{ id: 1 }] })));
    render(await MarketingCampaignBoard());
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить UTM-атрибуцию");
    expect(screen.queryByText("Нет кампаний")).not.toBeInTheDocument();
  });

  it("не отправляет запрос без сессии, если её получение завершилось ошибкой", async () => {
    authHeaders.mockRejectedValue(new Error("private session detail"));
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", fetcher);
    render(await MarketingCampaignBoard());
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить UTM-атрибуцию");
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.queryByText(/private session detail/)).not.toBeInTheDocument();
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
