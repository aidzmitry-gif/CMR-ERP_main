import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingFxRevaluation } from "./accounting-fx-revaluation";

const policy = { id: 4, effective_from: "2026-01-01", normative_verified: true, currency_revaluation: { monetary_accounts: ["60", "62"], gain_account: "91.1", loss_account: "91.2", gain_dimensions: {}, loss_dimensions: {}, reference: "Synthetic reviewed FX instruction" } };

afterEach(() => vi.unstubAllGlobals());

it("loads the period generation, previews documented rates and confirms the reviewed package", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => [{ month: "2026-09", generation: 3 }] })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        basis_digest: "a".repeat(64), digest: "b".repeat(64), period_generation: 3, source_line_count: 2,
        adjustments: [{ account: "62", currency: "USD", original_balance: "100.00", book_balance: "300.00", revalued_balance: "320.00", delta: "20.00", counterpart: "91.1", monetary_side: "debit", counterpart_side: "credit" }],
        posting_document: { lines: [{ account: "62", side: "debit", amount: "20.00" }, { account: "91.1", side: "credit", amount: "20.00" }] },
        confirmation_available: true, normative_verified: true, statutory_certified: false,
      }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ entry_id: 88 }) });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={policy} />);
  expect(await screen.findByText("Валютная переоценка · 2026-09")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Курс 1"), { target: { value: "3.20" } });
  fireEvent.change(screen.getByLabelText("Источник курса 1"), { target: { value: "Synthetic central-bank evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать переоценку" }));
  expect(await screen.findByText(/62 USD/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить пакет" }));
  expect(await screen.findByRole("status")).toHaveTextContent("проводка №88");
  expect(fetcher).toHaveBeenCalledWith("/api/accounting/organizations/7/periods/2026-09/fx-revaluation-confirm", expect.objectContaining({ method: "POST" }));
});

it("shows the explicit policy blocker instead of choosing accounts", () => {
  render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={{ ...policy, currency_revaluation: null }} />);
  expect(screen.getByText(/нет явных денежных счетов/)).toBeInTheDocument();
});

it("fills the official rate and scale without posting, and invalidates an edited preview", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ currency: "USD", date: "2026-09-30", official_rate: "3.1234", scale: 100, source: "NBRB" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ adjustments: [], source_line_count: 0, confirmation_available: true }) });
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={policy} />);
  fireEvent.click(screen.getByRole("button", { name: "Получить курс НБРБ 1" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Курс НБРБ загружен");
  expect(screen.getByLabelText("Курс 1")).toHaveValue("3.1234");
  expect(screen.getByLabelText("Масштаб курса 1")).toHaveValue(100);
  expect(screen.getByLabelText("Источник курса 1")).toHaveValue("НБРБ USD 2026-09-30");
  expect(fetcher).toHaveBeenLastCalledWith("/api/system/fx/USD?on=2026-09-30", { cache: "no-store" });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать переоценку" }));
  expect(await screen.findByRole("button", { name: "Подтвердить пакет" })).toBeEnabled();
  const payload = JSON.parse(fetcher.mock.calls[2][1].body);
  expect(payload.rates[0]).toMatchObject({ rate: "3.1234", rate_scale: 100 });
  fireEvent.change(screen.getByLabelText("Курс 1"), { target: { value: "3.5" } });
  expect(screen.queryByRole("button", { name: "Подтвердить пакет" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Источник курса 1")).toHaveValue("");
});

it("rejects mismatched quote data without replacing a manually entered rate", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ currency: "EUR", date: "2026-09-30", official_rate: "3.2", scale: 1, source: "NBRB" }) }));
  render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={policy} />);
  fireEvent.change(screen.getByLabelText("Курс 1"), { target: { value: "3.1" } });
  fireEvent.click(screen.getByRole("button", { name: "Получить курс НБРБ 1" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.getByLabelText("Курс 1")).toHaveValue("3.1");
});

it("does not apply a delayed quote after changing the organization", async () => {
  let resolveQuote!: (value: unknown) => void;
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] })
    .mockReturnValueOnce(new Promise((resolve) => { resolveQuote = resolve; }))
    .mockResolvedValueOnce({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={policy} />);
  fireEvent.click(screen.getByRole("button", { name: "Получить курс НБРБ 1" }));
  view.rerender(<AccountingFxRevaluation org="8" month="2026-09" date="2026-09-30" policy={policy} />);
  await act(async () => resolveQuote({ ok: true, json: async () => ({ currency: "USD", date: "2026-09-30", official_rate: "3.1234", scale: 100, source: "NBRB" }) }));
  expect(screen.getByLabelText("Курс 1")).toHaveValue("");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Получить курс НБРБ 1" })).toBeEnabled();
});

it("requires positive settlement amounts and a new documented rate when currency changes", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/accounts?") ? [{ code: "62", title: "Customers", required_dimensions: [] }] : [] })));
  const configured = { ...policy, currency_revaluation: { ...policy.currency_revaluation, settlement_allocation: "proportional_carrying" as const, settlement_rate_date: "posting_date" as const } };
  render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-30" policy={configured} />);
  await screen.findByRole("option", { name: "62 · Customers" });
  fireEvent.change(screen.getByLabelText("Денежный счёт валютного погашения"), { target: { value: "62" } });
  fireEvent.change(screen.getByLabelText("Курс валютного погашения"), { target: { value: "3.2" } });
  fireEvent.change(screen.getByLabelText("Источник курса валютного погашения"), { target: { value: "Reviewed rate document" } });
  const button = screen.getByRole("button", { name: "Рассчитать погашение" });
  for (const amount of ["0", "-1", "invalid", "Infinity"]) {
    fireEvent.change(screen.getByLabelText("Сумма валютного погашения"), { target: { value: amount } });
    expect(button).toBeDisabled();
  }
  fireEvent.change(screen.getByLabelText("Сумма валютного погашения"), { target: { value: "50.00" } });
  expect(button).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Валюта валютного погашения"), { target: { value: "EUR" } });
  expect(screen.getByLabelText("Курс валютного погашения")).toHaveValue("");
  expect(screen.getByLabelText("Источник курса валютного погашения")).toHaveValue("");
  expect(button).toBeDisabled();
});

it("does not show a delayed settlement preview after an operation-date change", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn((url: string) => {
    if (url.endsWith("/fx-settlement/preview")) return new Promise((resolve) => { finish = resolve; });
    return Promise.resolve({ ok: true, json: async () => url.includes("/accounts?") ? [{ code: "62", title: "Customers", required_dimensions: [] }] : [] });
  });
  vi.stubGlobal("fetch", fetcher);
  const configured = { ...policy, currency_revaluation: { ...policy.currency_revaluation, settlement_allocation: "proportional_carrying" as const, settlement_rate_date: "posting_date" as const } };
  const view = render(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-15" policy={configured} />);
  await screen.findByRole("option", { name: "62 · Customers" });
  for (const [label, value] of [["Денежный счёт валютного погашения", "62"], ["Сумма валютного погашения", "50"], ["Курс валютного погашения", "3.2"], ["Источник курса валютного погашения", "Reviewed rate document"]]) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать погашение" }));
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/fx-settlement/preview"), expect.objectContaining({ body: expect.stringContaining('"posting_date":"2026-09-15"') }));
  view.rerender(<AccountingFxRevaluation org="7" month="2026-09" date="2026-09-16" policy={configured} />);
  await act(async () => finish({ ok: true, json: async () => ({ book_balance: "300", allocated_book_amount: "150", documentary_amount: "160", exchange_difference: "10", remaining_original: "50", remaining_book_amount: "150" }) }));
  expect(screen.queryByText(/Балансовая стоимость позиции/)).not.toBeInTheDocument();
  expect(screen.getByText("Дата отражения: 2026-09-16")).toBeInTheDocument();
  expect(screen.getByLabelText("Сумма валютного погашения")).toHaveValue("");
});
