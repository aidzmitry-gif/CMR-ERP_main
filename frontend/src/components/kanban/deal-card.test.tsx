import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/channels", () => ({ ChannelRow: () => <div data-testid="channels" /> }));

import { DealCard } from "@/components/kanban/deal-card";
import type { Deal } from "@/lib/types";

const deal: Deal = {
  id: "1",
  number: "CRM-1",
  company: "ООО Карта",
  description: "Поставка металлопроката",
  amount: 850000,
  priority: "Высокий",
  owner: "Иванов И.И.",
  nextStep: "Звонок",
};

describe("DealCard", () => {
  it("показывает номер, компанию, приоритет, сумму и следующий шаг", () => {
    render(<DealCard deal={deal} />);
    expect(screen.getByText("№ CRM-1")).toBeInTheDocument();
    expect(screen.getByText("ООО Карта")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText(/850\D?000/)).toBeInTheDocument();
    expect(screen.getByText(/Звонок/)).toBeInTheDocument();
  });

  it("ведёт ссылкой на карточку сделки", () => {
    render(<DealCard deal={deal} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/crm/deals/1");
  });
});
