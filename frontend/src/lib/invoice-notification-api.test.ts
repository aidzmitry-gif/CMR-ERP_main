import { afterEach, expect, it, vi } from "vitest";

import { fetchInvoiceNotifications, prepareInvoiceNotificationEmail, sendInvoiceNotificationEmail } from "./invoice-notification-api";

afterEach(() => vi.unstubAllGlobals());

it("rejects a prepared email from another deal", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...email, deal_id: 502 })));
  await expect(prepareInvoiceNotificationEmail(7, "501", 4)).rejects.toThrow(/некорректное письмо/);
});

it("rejects a send response for a different email", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok({ ...email, id: "email-55" })));
  await expect(sendInvoiceNotificationEmail("501", "email-44")).rejects.toThrow(/некорректное письмо/);
});
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const notification = { id: 4, organization_id: 7, deal_id: 501, document_id: 100, document_version: 2, event_id: 9, event_type: "sales.invoice.cancelled", business_key: "cancelled:abc", channel: "email", recipient: "buyer@example.com", state: "pending", reason: null, payload: {}, created_at: "2026-09-10T10:00:00Z" };
const email = { id: "email-44", deal_id: 501, sender: "erp@example.com", to: ["buyer@example.com"], cc: [], subject: "Счёт отменён", body: "text", attachments: [], status: "prepared", created_at: "2026-09-10T10:00:00Z", confirmed_at: null, accepted_at: null, next_attempt_at: null, attempt_count: 0, last_reason: null, message_id: null };

it("reads only the selected invoice notification and validates the organization", async () => {
  const fetchMock = vi.fn().mockResolvedValue(ok([notification, { ...notification, id: 5, document_id: 101 }]));
  vi.stubGlobal("fetch", fetchMock);
  await expect(fetchInvoiceNotifications(7, "501", 100)).resolves.toHaveLength(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/sales/deals/501/invoice-notifications", { cache: "no-store" });
});

it("prepares then explicitly confirms the email", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(ok(email)).mockResolvedValueOnce(ok({ ...email, status: "queued" }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(prepareInvoiceNotificationEmail(7, "501", 4)).resolves.toMatchObject({ id: "email-44", status: "prepared" });
  await expect(sendInvoiceNotificationEmail("501", "email-44")).resolves.toMatchObject({ id: "email-44", status: "queued" });
  expect(fetchMock.mock.calls[1]).toEqual(["/api/sales/deals/501/emails/email-44/send", { method: "POST" }]);
});

it("rejects a foreign notification instead of rendering it", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok([{ ...notification, organization_id: 8 }])));
  await expect(fetchInvoiceNotifications(7, "501", 100)).rejects.toThrow(/чужое уведомление/);
});
