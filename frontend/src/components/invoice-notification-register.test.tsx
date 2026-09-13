import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { InvoiceNotificationRegister } from "./invoice-notification-register";

afterEach(() => vi.unstubAllGlobals());
const notification = { id: 4, organization_id: 7, deal_id: 501, document_id: 100, document_version: 2, event_id: 9, event_type: "sales.invoice.cancelled", business_key: "cancelled:abc", channel: "email", recipient: "buyer@example.com", state: "pending", reason: null, payload: {}, created_at: "2026-09-10T10:00:00Z" };
const email = { id: "email-44", deal_id: 501, sender: "erp@example.com", to: ["buyer@example.com"], cc: [], subject: "Счёт отменён", body: "text", attachments: [], status: "prepared", created_at: "2026-09-10T10:00:00Z", confirmed_at: null, accepted_at: null, next_attempt_at: null, attempt_count: 0, last_reason: null, message_id: null };
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

it("prepares and separately confirms customer notification", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(response([notification])).mockResolvedValueOnce(response(email)).mockResolvedValueOnce(response({ ...email, status: "queued" }));
  vi.stubGlobal("fetch", fetchMock);
  render(<InvoiceNotificationRegister organizationId={7} dealId="501" documentId={100} />);
  await screen.findByText(/Аннулирование счёта/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Подготовить письмо" }));
  await screen.findByText(/Письмо: Подготовлено/);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить отправку письма" }));
  await screen.findByText(/Состояние почтовой очереди подтверждено/);
  expect(fetchMock.mock.calls[1][0]).toContain("prepare-email");
  expect(fetchMock.mock.calls[2][0]).toContain("/emails/email-44/send");
});

it("clears the previous invoice immediately while the new register is loading", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(response([notification]))
    .mockResolvedValueOnce(response(email)).mockImplementationOnce(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<InvoiceNotificationRegister organizationId={7} dealId="501" documentId={100} />);
  await screen.findByText(/Аннулирование счёта/);
  fireEvent.click(screen.getByRole("button", { name: "Подготовить письмо" }));
  await screen.findByText(/Письмо: Подготовлено/);
  view.rerender(<InvoiceNotificationRegister organizationId={7} dealId="501" documentId={101} />);
  expect(screen.queryByText(/Аннулирование счёта/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Подтвердить отправку письма" })).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Загрузка решений");
});

it("shows a blocked decision without offering a send action", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([{ ...notification, state: "blocked", recipient: null, reason: "recipient_email_missing_or_invalid" }])));
  render(<InvoiceNotificationRegister organizationId={7} dealId="501" documentId={100} />);
  await screen.findByText(/Требуется сверка/);
  expect(screen.getByText(/recipient_email_missing_or_invalid/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Подготовить письмо|Подтвердить отправку/ })).toBeNull();
});
