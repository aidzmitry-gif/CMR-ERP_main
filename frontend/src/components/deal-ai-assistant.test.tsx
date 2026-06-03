import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ aiAssist: vi.fn() }));

import { DealAiAssistant } from "@/components/deal-ai-assistant";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("DealAiAssistant", () => {
  it("генерирует резюме и показывает результат", async () => {
    mock(api.aiAssist).mockResolvedValue("AI: резюме готово");
    render(<DealAiAssistant dealId="1" />);
    fireEvent.click(screen.getByRole("button", { name: "Резюме сделки" }));
    await waitFor(() => expect(api.aiAssist).toHaveBeenCalledWith("1", "summary"));
    expect(await screen.findByText("AI: резюме готово")).toBeInTheDocument();
  });

  it("показывает заглушку при выключенном AI", async () => {
    mock(api.aiAssist).mockResolvedValue(null);
    render(<DealAiAssistant dealId="1" />);
    fireEvent.click(screen.getByRole("button", { name: "Следующий шаг" }));
    await waitFor(() => expect(api.aiAssist).toHaveBeenCalledWith("1", "next_step"));
    expect(await screen.findByText(/AI-слой выключен/)).toBeInTheDocument();
  });
});
