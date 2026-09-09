import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CurrencyProvider, useCurrency } from "./currency-context";

function Consumer() {
  const { fmt, setCompany } = useCurrency();
  return <><button onClick={() => setCompany("pl")}>EUR</button><output>{fmt(355)}</output></>;
}

beforeEach(() => vi.stubGlobal("localStorage", { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());

it("uses the official dated quote after switching company", async () => {
  const on = new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Minsk" }).format(new Date());
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ currency: "EUR", date: on, rate: "3.55" }) }));
  render(<CurrencyProvider><Consumer /></CurrencyProvider>);
  fireEvent.click(screen.getByText("EUR"));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("100 €"));
});

it("shows unavailable on network error instead of a demo rate", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<CurrencyProvider><Consumer /></CurrencyProvider>);
  fireEvent.click(screen.getByText("EUR"));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Курс недоступен"));
});
