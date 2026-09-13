import { expect, it } from "vitest";
import { trialBalanceCsv, type ExportReport } from "./accounting-export";

const report: ExportReport = { organization_id: 7, from: "2026-09-01", to: "2026-09-30", status: "preliminary", pending_documents: 2, trial_balance: [{ account: "001", title: '=HYPERLINK("https://invalid")', currency: "USD", dimensions: { warehouse: "A;B", counterparty: "Name\nquoted\"" }, off_balance: true, opening: "-9007199254740993.01", debit: "1.02", credit: "0.00", closing: "-9007199254740991.99", original_opening: "-1.01", quantity_opening: "0.000001" }] };

it("preserves exact decimal strings, source currency, quantities and account codes", () => {
  const csv = trialBalanceCsv(report);
  expect(csv.startsWith("\uFEFF")).toBe(true);
  expect(csv).toContain('"001"');
  expect(csv).toContain('"-9007199254740993.01";"1.02";"0.00";"-9007199254740991.99"');
  expect(csv).toContain('"-1.01";"";"";"";"0.000001"');
  expect(csv).toContain('"USD";"Да"');
  expect(csv).toContain('"report";"7";"2026-09-01";"2026-09-30";"preliminary";"2";');
});

it("escapes text and neutralizes formula prefixes without altering negative amounts", () => {
  const csv = trialBalanceCsv(report);
  expect(csv).toContain('"\'=HYPERLINK(""https://invalid"")"');
  expect(csv).toContain('"{');
  expect(csv).not.toContain('"\'-9007199254740993.01"');
  for (const title of ["+cmd", "-cmd", "@SUM(1)", "\t=1", "\r=1"]) {
    expect(trialBalanceCsv({ ...report, trial_balance: [{ ...report.trial_balance[0], title }] })).toContain(`"'${title}"`);
  }
});

it("retains metadata for empty books and rejects invalid monetary values", () => {
  expect(trialBalanceCsv({ ...report, trial_balance: [] }).split("\r\n")).toHaveLength(3);
  expect(() => trialBalanceCsv({ ...report, trial_balance: [{ ...report.trial_balance[0], debit: "=1+1" }] })).toThrow("Некорректная сумма");
});
