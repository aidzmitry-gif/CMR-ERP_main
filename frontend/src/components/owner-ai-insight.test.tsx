import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchOwnerInsight: vi.fn() }));

import { OwnerAiInsight } from "@/components/owner-ai-insight";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("OwnerAiInsight", () => {
  it("генерирует AI-инсайт", async () => {
    mock(api.fetchOwnerInsight).mockResolvedValue("Здоровье бизнеса в норме");
    render(<OwnerAiInsight />);
    fireEvent.click(screen.getByText("Сгенерировать"));
    await waitFor(() => expect(api.fetchOwnerInsight).toHaveBeenCalled());
    expect(await screen.findByText("Здоровье бизнеса в норме")).toBeInTheDocument();
  });

  it("показывает заглушку при выключенном AI", async () => {
    mock(api.fetchOwnerInsight).mockResolvedValue(null);
    render(<OwnerAiInsight />);
    fireEvent.click(screen.getByText("Сгенерировать"));
    expect(await screen.findByText(/AI-слой выключен/)).toBeInTheDocument();
  });
});
