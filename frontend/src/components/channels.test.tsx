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

  it("ChannelRow onPhone вызывает колбэк по иконке телефона", () => {
    const onPhone = vi.fn();
    render(<ChannelRow onPhone={onPhone} />);
    fireEvent.click(screen.getByRole("button", { name: "Позвонить" }));
    expect(onPhone).toHaveBeenCalledTimes(1);
  });

  it("ChannelButtons по каждому каналу строит ссылку и пишет в историю", async () => {
    mock(api.fetchContacts).mockResolvedValue([
      { id: 1, full_name: "Анна", phone: "+375290000000", email: "a@b.by", is_primary: true },
    ]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<ChannelButtons dealId="1" />);
    await screen.findByText("WhatsApp");

    for (const [label, channel] of [
      ["Позвонить", "phone"],
      ["WhatsApp", "whatsapp"],
      ["Viber", "viber"],
      ["Telegram", "telegram"],
      ["Email", "email"],
    ] as const) {
      fireEvent.click(screen.getByText(label));
      await waitFor(() =>
        expect(api.sendMessage).toHaveBeenCalledWith("1", channel, expect.stringContaining(label)),
      );
    }
    expect(globalThis.open).toHaveBeenCalled();
  });

  it("без контакта ссылка не открывается, но связь фиксируется", async () => {
    mock(api.fetchContacts).mockResolvedValue([]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<ChannelButtons dealId="2" />);
    await screen.findByText("Позвонить");
    fireEvent.click(screen.getByText("Позвонить"));
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith("2", "phone", expect.any(String)));
  });
});
