import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DealDocumentCard } from "@/components/deal-document-card";
import type { DealDoc } from "@/lib/api";

const doc: DealDoc = {
  id: 7, kind: "contract", number: "DOG-7", status: "draft", onec_ref: null,
  amount: 100, valid_until: null, reserve_status: "none", payment_terms: null,
  delivery_terms: null, draft_edit_token: "a".repeat(64),
};

afterEach(() => vi.unstubAllGlobals());

it("открывает документ по номеру, сохраняет и закрывает только по точной квитанции", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ document_id: 7, items: [], next_before_id: null }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ id: 7, status: "draft", payment_terms: "30 дней", delivery_terms: null, draft_edit_token: "b".repeat(64) }) });
  vi.stubGlobal("fetch", fetchMock);
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<DealDocumentCard doc={doc} refresh={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть документ № DOG-7" }));
  expect(await screen.findByText("Зафиксированных изменений нет; более ранние правки могут быть неизвестны.")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "Условия оплаты" }), { target: { value: "30 дней" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(screen.queryByRole("region", { name: "Карточка документа DOG-7" })).toBeNull();
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    payment_terms: "30 дней", delivery_terms: null, expected_edit_token: "a".repeat(64),
  });
});

it("после конфликта оставляет изменённые поля и карточку открытыми", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ document_id: 7, items: [], next_before_id: null }) })
    .mockResolvedValueOnce({ ok: false, status: 409 }));
  render(<DealDocumentCard doc={doc} refresh={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть документ № DOG-7" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Условия оплаты" }), { target: { value: "Моя версия" } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить и закрыть" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Черновик изменился");
  expect(screen.getByRole("textbox", { name: "Условия оплаты" })).toHaveValue("Моя версия");
  expect(screen.getByRole("region", { name: "Карточка документа DOG-7" })).toBeInTheDocument();
});
