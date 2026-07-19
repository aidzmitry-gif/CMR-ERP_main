import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/reference-data", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/reference-data")>()),
  decideApproval: vi.fn(),
}));

import { SpravAdmin } from "@/components/erp/spravochniki/sprav-admin";
import * as ref from "@/lib/reference-data";
import type { ApprovalRow } from "@/lib/reference-data";

const rows: ApprovalRow[] = [
  {
    id: 1,
    kind: "reference.change",
    entity_ref: "ref_vat_rate:НДС20",
    subject: "Ставка НДС 20% → 22%",
    route: "financier",
    status: "pending",
    requested_by: "Иванов И.И.",
    created_at: "2026-07-10T09:15:00",
    due_at: null,
  },
  {
    id: 2,
    kind: "reference.change",
    entity_ref: "ref_tnved:8517",
    subject: "Пошлина ТН ВЭД 8517",
    route: "controller",
    status: "pending",
    requested_by: "",
    created_at: null,
    due_at: null,
  },
];

beforeEach(() => vi.clearAllMocks());

describe("SpravAdmin", () => {
  it("пустая очередь: показывает заглушку и не рендерит таблицу", () => {
    render(<SpravAdmin initial={[]} />);
    expect(screen.getByText("Очередь пуста")).toBeInTheDocument();
    expect(
      screen.getByText("Нет правок справочников, ожидающих согласования."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("рендерит строки очереди: тему, объект, роль, автора и форматированную дату; пустой автор/дата → «—»", () => {
    render(<SpravAdmin initial={rows} />);
    expect(screen.getByText("Ставка НДС 20% → 22%")).toBeInTheDocument();
    expect(screen.getByText("ref_vat_rate:НДС20")).toBeInTheDocument();
    expect(screen.getByText("financier")).toBeInTheDocument();
    expect(screen.getByText("Иванов И.И.")).toBeInTheDocument();
    // ISO "2026-07-10T09:15:00" -> "2026-07-10 09:15"
    expect(screen.getByText("2026-07-10 09:15")).toBeInTheDocument();
    // строка 2: requested_by="" и created_at=null -> оба поля "—"
    const row2 = screen.getByText("Пошлина ТН ВЭД 8517").closest("tr");
    expect(row2).not.toBeNull();
    const dashes = row2!.querySelectorAll("td");
    // requested_by (4-я колонка) и created_at (5-я) должны быть "—"
    expect(dashes[3].textContent).toBe("—");
    expect(dashes[4].textContent).toBe("—");
  });

  it("одобрение: успешный ответ убирает строку из очереди и показывает тост «Правка одобрена»", async () => {
    vi.mocked(ref.decideApproval).mockResolvedValue(true);
    render(<SpravAdmin initial={rows} />);
    screen.getAllByRole("button", { name: "Одобрить" })[0].click();
    expect(ref.decideApproval).toHaveBeenCalledWith(1, true);
    await waitFor(() => expect(screen.getByText("Правка одобрена")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.queryByText("Ставка НДС 20% → 22%")).not.toBeInTheDocument(),
    );
    // вторая строка осталась
    expect(screen.getByText("Пошлина ТН ВЭД 8517")).toBeInTheDocument();
  });

  it("отклонение: успешный ответ убирает строку и показывает тост «Правка отклонена»", async () => {
    vi.mocked(ref.decideApproval).mockResolvedValue(true);
    render(<SpravAdmin initial={rows} />);
    screen.getAllByRole("button", { name: "Отклонить" })[1].click();
    expect(ref.decideApproval).toHaveBeenCalledWith(2, false);
    await waitFor(() => expect(screen.getByText("Правка отклонена")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.queryByText("Пошлина ТН ВЭД 8517")).not.toBeInTheDocument(),
    );
  });

  it("ошибка сервера/нет права: строка остаётся в очереди и показывается текст ошибки", async () => {
    vi.mocked(ref.decideApproval).mockResolvedValue(false);
    render(<SpravAdmin initial={rows} />);
    screen.getAllByRole("button", { name: "Одобрить" })[0].click();
    await waitFor(() =>
      expect(
        screen.getByText("Ошибка: нет права на согласование или сервер недоступен"),
      ).toBeInTheDocument(),
    );
    // строка НЕ удалена
    expect(screen.getByText("Ставка НДС 20% → 22%")).toBeInTheDocument();
  });
});
