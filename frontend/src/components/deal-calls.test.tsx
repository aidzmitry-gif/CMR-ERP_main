import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchDealCalls: vi.fn() }));

import { DealCalls } from "@/components/deal-calls";
import { fetchDealCalls } from "@/lib/api";

afterEach(() => vi.clearAllMocks());

describe("DealCalls", () => {
  it("показывает понятное пустое состояние и запрашивает звонки конкретной сделки", async () => {
    vi.mocked(fetchDealCalls).mockResolvedValue([]);

    render(await DealCalls({ dealId: 42, roles: "sales", accessToken: "token" }));

    expect(fetchDealCalls).toHaveBeenCalledWith(42, "sales", "token");
    expect(screen.getByText("Звонки")).toBeInTheDocument();
    expect(screen.getByText(/Пока нет звонков по этой сделке/)).toBeInTheDocument();
  });

  it("показывает направление, статус, длительность и ссылку на запись", async () => {
    vi.mocked(fetchDealCalls).mockResolvedValue([
      {
        id: 7,
        call_id: "CALL-7",
        direction: "in",
        phone_e164: "+375291112233",
        status: "ended",
        duration_sec: 65,
        started_at: "2026-07-21T10:30:00Z",
        recording_url: "https://calls.example.test/recording/7",
      },
    ]);

    render(await DealCalls({ dealId: "42" }));

    expect(screen.getByText("Вх. +375291112233")).toBeInTheDocument();
    expect(screen.getByText("завершён")).toBeInTheDocument();
    expect(screen.getByText("· 1:05")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Запись разговора" })).toHaveAttribute(
      "href",
      "https://calls.example.test/recording/7",
    );
  });
});
