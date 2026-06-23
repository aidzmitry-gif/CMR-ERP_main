import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { IncomingCallCard } from "@/components/calls/incoming-call-card";
import type { CallCard } from "@/lib/api";

const base: CallCard = {
  id: 1,
  call_id: "c1",
  direction: "in",
  phone: "+375291112233",
  owner: "Иванов П.П.",
  deal_id: 7,
  status: "ringing",
};

const noop = {
  onClose: vi.fn(),
  onComment: vi.fn(),
  onResult: vi.fn(),
  onLinkDeal: vi.fn(),
  onCreateDeal: vi.fn(),
  onCreateLead: vi.fn(),
};

describe("IncomingCallCard", () => {
  it("известный клиент → владелец + сделка; создать сделку", () => {
    const onCreateDeal = vi.fn();
    render(<IncomingCallCard card={base} {...noop} onCreateDeal={onCreateDeal} />);
    expect(screen.getByText("Входящий звонок")).toBeInTheDocument();
    expect(screen.getByText(/Иванов П\.П\./)).toBeInTheDocument();
    expect(screen.getByText(/Сделка #7/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Создать сделку"));
    expect(onCreateDeal).toHaveBeenCalled();
  });

  it("новый номер → создать лид", () => {
    const onCreateLead = vi.fn();
    render(
      <IncomingCallCard card={{ ...base, owner: "", deal_id: null }} {...noop} onCreateLead={onCreateLead} />,
    );
    expect(screen.getByText("Новый номер")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Создать лид"));
    expect(onCreateLead).toHaveBeenCalled();
  });

  it("комментарий по звонку сохраняется", () => {
    const onComment = vi.fn();
    render(<IncomingCallCard card={base} {...noop} onComment={onComment} />);
    fireEvent.change(screen.getByPlaceholderText("Комментарий по звонку…"), {
      target: { value: "перезвонить в 15:00" },
    });
    fireEvent.click(screen.getByText("Сохранить комментарий"));
    expect(onComment).toHaveBeenCalledWith("перезвонить в 15:00");
  });
});
