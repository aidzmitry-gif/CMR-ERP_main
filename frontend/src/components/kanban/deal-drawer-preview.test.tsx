import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({
  issueDocument: vi.fn(),
  fetchDocuments: vi.fn().mockResolvedValue([]),
  updateDeal: vi.fn().mockResolvedValue(true),
  fetchContacts: vi.fn().mockResolvedValue([]),
  fetchSkus: vi.fn().mockResolvedValue([]),
  fetchStock: vi.fn().mockResolvedValue([]),
}));

import { DealDrawerPreview } from "@/components/kanban/deal-drawer-preview";
import * as api from "@/lib/api";
import type { Deal, Stage } from "@/lib/types";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const deal: Deal = {
  id: "1",
  number: "CRM-1",
  company: "ООО Карта",
  description: "Поставка металлопроката",
  amount: 1000,
  priority: "Средний",
  owner: "Иванов И.И.",
};

const stages: Stage[] = [
  { id: "invoice", title: "Счёт отправлен", color: "#000", count: 1, sum: 1000, deals: [deal] },
];

function renderDrawer(onUpdateFields = vi.fn()) {
  render(
    <DealDrawerPreview
      deal={deal}
      stages={stages}
      onClose={() => {}}
      onMoveStage={() => {}}
      onUpdateFields={onUpdateFields}
      onAddTask={() => {}}
      onWin={() => {}}
      onLose={() => {}}
      now={Date.now()}
    />,
  );
  return { onUpdateFields };
}

beforeEach(() => {
  vi.clearAllMocks();
  mock(api.fetchDocuments).mockResolvedValue([]);
  vi.stubGlobal(
    "open",
    vi.fn(() => ({ location: { href: "" }, close: vi.fn() })),
  );
});

describe("DealDrawerPreview — слайс 6 (A): авто-шаг после счёта", () => {
  it("успешный счёт → onUpdateFields и updateDeal с next_step «Проверить оплату…» (+3 дн)", async () => {
    mock(api.issueDocument).mockResolvedValue({
      ok: true,
      message: "✅ Счёт СЧ-1 выставлен",
      renderUrl: "/api/sales/documents/9/render",
    });
    const { onUpdateFields } = renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Счёт" }));

    expect(await screen.findByText(/Шаг: Проверить оплату/)).toBeInTheDocument();
    expect(api.issueDocument).toHaveBeenCalledWith("1", "invoice");
    expect(api.updateDeal).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({
        next_step: expect.stringContaining("Проверить оплату"),
        next_step_at: expect.any(String),
      }),
    );
    expect(onUpdateFields).toHaveBeenCalledWith(
      "1",
      expect.objectContaining({ next_step: expect.stringContaining("Проверить оплату") }),
    );
  });

  it("неуспешный счёт (ok=false) — updateDeal НЕ вызван", async () => {
    mock(api.issueDocument).mockResolvedValue({ ok: false, message: "⚠️ Не удалось выставить счёт" });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Счёт" }));
    await screen.findByText("⚠️ Не удалось выставить счёт");
    expect(api.updateDeal).not.toHaveBeenCalled();
  });

  it("договор — updateDeal НЕ вызван (авто-шаг только для счёта)", async () => {
    mock(api.issueDocument).mockResolvedValue({
      ok: true,
      message: "✅ Договор ДГ-1 отправлен на согласование",
    });
    renderDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Договор" }));
    await screen.findByText("✅ Договор ДГ-1 отправлен на согласование");
    expect(api.updateDeal).not.toHaveBeenCalled();
  });
});

describe("DealDrawerPreview — слайс 6 (B): блок «Документы»", () => {
  it("нет документов (или ошибка фетча — fetchDocuments сам гасит её в []) — блок не рендерится", async () => {
    renderDrawer();
    await waitFor(() => expect(api.fetchDocuments).toHaveBeenCalledWith("1"));
    expect(screen.queryByText("Документы")).toBeNull();
  });

  it("счёт с valid_until в прошлом — «просрочен N дн», бейдж «резерв», ссылка «открыть»", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      {
        id: 9,
        kind: "invoice",
        number: "СЧ-1",
        status: "posted",
        onec_ref: null,
        amount: 5000,
        valid_until: "2000-01-01",
        reserve_status: "reserved",
      },
    ]);
    renderDrawer();
    expect(await screen.findByText("Документы")).toBeInTheDocument();
    expect(screen.getByText(/Счёт СЧ-1/)).toBeInTheDocument();
    expect(screen.getByText(/просрочен \d+ дн/)).toBeInTheDocument();
    expect(screen.getByText("резерв")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "открыть" })).toHaveAttribute(
      "href",
      "/api/sales/documents/9/render",
    );
  });

  it("договор — номер и статус", async () => {
    mock(api.fetchDocuments).mockResolvedValue([
      {
        id: 4,
        kind: "contract",
        number: "ДГ-2",
        status: "pending_approval",
        onec_ref: null,
        amount: 1,
        valid_until: null,
        reserve_status: "none",
      },
    ]);
    renderDrawer();
    expect(await screen.findByText(/Договор ДГ-2/)).toBeInTheDocument();
    expect(screen.getByText("На согласовании")).toBeInTheDocument();
  });
});
