import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("does not open a previous deal's late contact", async () => {
    let finish!: (rows: api.DealContact[]) => void;
    vi.mocked(api.fetchContacts).mockReturnValueOnce(new Promise(resolve => {finish=resolve;})).mockResolvedValueOnce([]);
    const view=render(<ChannelButtons dealId="1" />);
    view.rerender(<ChannelButtons dealId="2" />);
    await act(async () => finish([{id:1,full_name:"Previous",phone:"+375290000000",email:"",is_primary:true}]));
    fireEvent.click(screen.getByRole("button",{name:"Позвонить"}));
    expect(globalThis.open).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });
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

  it("ChannelButtons opens channel links without claiming a conversation occurred", async () => {
    mock(api.fetchContacts).mockResolvedValue([
      { id: 1, full_name: "Анна", phone: "+375290000000", email: "a@b.by", is_primary: true },
    ]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<ChannelButtons dealId="1" />);
    await waitFor(() => expect(screen.getByRole("button", { name:"WhatsApp" })).toBeEnabled());

    for (const [label] of [
      ["Позвонить", "phone"],
      ["WhatsApp", "whatsapp"],
      ["Viber", "viber"],
      ["Telegram", "telegram"],
      ["Email", "email"],
    ] as const) {
      fireEvent.click(screen.getByText(label));
    }
    expect(globalThis.open).toHaveBeenCalledTimes(5);
    expect(api.sendMessage).not.toHaveBeenCalled();
  });

  it("without a contact no link opens and no history is invented", async () => {
    mock(api.fetchContacts).mockResolvedValue([]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<ChannelButtons dealId="2" />);
    await screen.findByText("Позвонить");
    fireEvent.click(screen.getByText("Позвонить"));
    expect(screen.getByRole("button", { name:"Позвонить" })).toBeDisabled();
    expect(globalThis.open).not.toHaveBeenCalled();
    expect(api.sendMessage).not.toHaveBeenCalled();
  });
});
