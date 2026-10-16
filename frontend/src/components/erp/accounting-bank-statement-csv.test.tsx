import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingBankStatementCsv } from "./accounting-bank-statement-csv";

const content = "external_id,direction,operation_date,amount,currency,counterparty_name,counterparty_identifier,purpose\none,receipt,2026-09-01,12.30,BYN,,,Sale\n";
const digest = "a".repeat(64);
const reference = "sha256:" + "b".repeat(64);
const validPreview = { organization_id: 1, valid: true, preview_digest: digest, source_reference: reference, valid_count: 1, totals: { receipt: "12.30", payment: "0.00" }, errors: [] };

function file(): File {
  return { size: content.length, arrayBuffer: async () => new TextEncoder().encode(content).buffer } as File;
}

function ready() {
  fireEvent.change(screen.getByLabelText("Банк для CSV"), { target: { value: "test-bank" } });
  fireEvent.change(screen.getByLabelText("Наш банковский счёт для CSV"), { target: { value: "BY-TEST" } });
  fireEvent.change(screen.getByLabelText("Основание принадлежности счёта для CSV"), { target: { value: "Проверенное основание" } });
  fireEvent.change(screen.getByLabelText("Файл банковской выписки CSV"), { target: { files: [file()] } });
}

function response(value: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => value };
}

afterEach(() => vi.unstubAllGlobals());

it("rejects a preview that does not prove the selected organization", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...validPreview, organization_id: 2 })));
  render(<AccountingBankStatementCsv org="1" disabled={false} onImported={vi.fn().mockResolvedValue(undefined)} />);
  ready();
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить CSV" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Проверить CSV" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("выбранного юрлица");
  expect(screen.queryByRole("button", { name: "Сохранить строки выписки" })).not.toBeInTheDocument();
});

it("freezes an unverified confirmation and retries the exact command", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/preview")) return Promise.resolve(response(validPreview));
    if (fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/confirm")).length === 1) {
      return Promise.resolve(response({ organization_id: 1, source_reference: "sha256:" + "c".repeat(64), count: 1, source_transaction_ids: [7] }));
    }
    return Promise.resolve(response({ organization_id: 1, source_reference: reference, count: 1, source_transaction_ids: [7] }));
  });
  vi.stubGlobal("fetch", fetchMock);
  const imported = vi.fn().mockResolvedValue(undefined);
  render(<AccountingBankStatementCsv org="1" disabled={false} onImported={imported} />);
  ready();
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить CSV" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Проверить CSV" }));
  await screen.findByRole("button", { name: "Сохранить строки выписки" });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить строки выписки" }));
  expect(await screen.findByRole("button", { name: "Проверить результат сохранения" })).toBeEnabled();
  expect(screen.getByLabelText("Банк для CSV")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Проверить CSV" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Проверить результат сохранения" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Обработано строк: 1");
  expect(imported).toHaveBeenCalledOnce();
  const confirms = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/confirm"));
  expect(confirms).toHaveLength(2);
  expect(confirms[0][1]?.body).toBe(confirms[1][1]?.body);
});

it("keeps the import editable after a known validation rejection", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith("/preview")
    ? response(validPreview)
    : response({ detail: "CSV or import settings changed; preview again" }, 422)));
  vi.stubGlobal("fetch", fetchMock);
  render(<AccountingBankStatementCsv org="1" disabled={false} onImported={vi.fn().mockResolvedValue(undefined)} />);
  ready();
  await waitFor(() => expect(screen.getByRole("button", { name: "Проверить CSV" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Проверить CSV" }));
  await screen.findByRole("button", { name: "Сохранить строки выписки" });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить строки выписки" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("preview again");
  expect(screen.getByLabelText("Банк для CSV")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Сохранить строки выписки" })).toHaveTextContent("Сохранить строки выписки");
});
