import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ fetchContacts: vi.fn(), sendMessage: vi.fn() }));

import { ChannelButtons, ChannelRow } from "@/components/channels";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("open", vi.fn()); // window.open в jsdom — заглушка
});

describe("channels", () => {
  it("ChannelRow рендерит индикаторы каналов", () => {
    const { container } = render(<ChannelRow />);
    expect(container.querySelectorAll("span").length).toBeGreaterThanOrEqual(5);
  });

  it("ChannelButtons открывает связь и пишет в историю по основному контакту", async () => {
    mock(api.fetchContacts).mockResolvedValue([
      { id: 1, full_name: "Анна", phone: "+375290000000", email: "a@b.by", is_primary: true },
    ]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<ChannelButtons dealId="1" />);
    expect(await screen.findByText("WhatsApp")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Позвонить"));
    await waitFor(() =>
      expect(api.sendMessage).toHaveBeenCalledWith("1", "phone", expect.stringContaining("Позвонить")),
    );
  });
});
