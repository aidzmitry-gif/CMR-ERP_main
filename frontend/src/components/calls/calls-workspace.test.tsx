import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchCalls: vi.fn(), triggerIncomingCall: vi.fn() }));

import { CallsWorkspace } from "@/components/calls/calls-workspace";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("CallsWorkspace", () => {
  it("журнал звонков + симуляция входящего", async () => {
    mock(api.fetchCalls).mockResolvedValue([
      {
        id: 1,
        call_id: "c1",
        direction: "in",
        phone_e164: "+375291112233",
        owner: "Иванов П.П.",
        status: "ended",
        result: "Договорились",
        started_at: "2026-06-23T10:00:00",
      },
    ]);
    mock(api.triggerIncomingCall).mockResolvedValue(true);
    render(<CallsWorkspace />);
    expect(await screen.findByText("+375291112233")).toBeInTheDocument();
    expect(screen.getByText("Договорились")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Симулировать входящий"));
    await waitFor(() => expect(api.triggerIncomingCall).toHaveBeenCalled());
  });
});
