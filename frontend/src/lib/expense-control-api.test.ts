import { webcrypto } from "node:crypto";

import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { begin, dispatch, getUnmatchedActuals, hash, previewAttribution } from "./expense-control-api";

beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => { sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("accepts a signed unmatched row with an empty analytics string", async () => {
  const unsigned = {
    organization_id: 7,
    principal: "chief",
    year: 2026,
    month: 1,
    currency: "BYN",
    basis: "accrual",
    items: [{
      entry_id: 10,
      line_id: 12,
      posting_date: "2026-01-02",
      source: "expense-api",
      operation: "manual",
      account_code: "90.4",
      side: "debit",
      amount: "2.00",
      dimensions: { analytics: "" },
      reason: "нет статьи",
    }],
    next_after_line_id: 12,
  };
  const response = { ...unsigned, digest: await hash(unsigned) };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
  vi.stubGlobal("fetch", fetchMock);

  const result = await getUnmatchedActuals({ org: 7, principal: "chief" }, 2026, 1, "accrual", 12);

  expect(result.items[0].dimensions).toEqual({ analytics: "" });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/accounting/organizations/7/expense-actuals/unmatched?year=2026&month=1&currency=BYN&basis=accrual&after_line_id=12",
    { cache: "no-store" },
  );
});

it("sends a scoped preview and accepts only its signed response", async () => {
  const body = { source_line_id: 12, article_id: 5, effective_date: "2026-01-02" };
  const preview = {
    source_entry_id: 10, source_line_id: 12, article_id: 5, supersedes_id: null, effective_date: "2026-01-02", basis_digest: "a".repeat(64),
    source_snapshot: { entry_id: 10, source: "expense-api", source_version: 1, operation: "manual", posting_date: "2026-01-02", policy_id: 3,
      entry_digest: "b".repeat(64), line_id: 12, account_code: "90.4", account_title: "Расходы", category: "expense", cash: false,
      side: "debit", amount: "2.00", currency: "BYN", dimensions: { analytics: "" } },
    article_snapshot: { id: 5, code: "supplies", title: "Материалы", group_id: 2, group: { id: 2, code: "office", title: "Офис", active: true } },
  };
  const unsigned = { organization_id: 7, principal: "chief", preview };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...unsigned, digest: await hash(unsigned) }) });
  vi.stubGlobal("fetch", fetchMock);

  await expect(previewAttribution({ org: 7, principal: "chief" }, body)).resolves.toEqual(preview);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/accounting/organizations/7/expense-attributions/preview",
    { method: "POST", body: JSON.stringify(body), headers: { "Content-Type": "application/json", "X-Expected-Principal": "chief" }, cache: "no-store" },
  );
});

it("recovers the exact saved attribution through its dedicated receipt endpoint", async () => {
  const scope = { org: 7, principal: "chief" };
  const command = { request_key: "11111111-1111-4111-8111-111111111111", source_line_id: 12, article_id: 5, effective_date: "2026-01-02",
    expected_basis_digest: "a".repeat(64), evidence: "Проверен первичный документ", explanation: "Ручное разнесение" };
  const saved = await begin(scope, "attribution", command, null);
  const catalog = { revision: 1, groups: [{ id: 2, code: "office", title: "Офис", active: true }], articles: [{ id: 5, code: "supplies", title: "Материалы", group_id: 2, active: true }] };
  const contextUnsigned = { organization_id: 7, principal: "chief", catalog, role: "chief", approval_enabled: true, approval_blocker: null, template: [] };
  const result = {
    source_entry_id: 10, source_line_id: 12, article_id: 5, supersedes_id: null, effective_date: "2026-01-02", basis_digest: command.expected_basis_digest,
    source_snapshot: { entry_id: 10, source: "expense-api", source_version: 1, operation: "manual", posting_date: "2026-01-02", policy_id: 3,
      entry_digest: "b".repeat(64), line_id: 12, account_code: "90.4", account_title: "Расходы", category: "expense", cash: false,
      side: "debit", amount: "2.00", currency: "BYN", dimensions: {} },
    article_snapshot: { id: 5, code: "supplies", title: "Материалы", group_id: 2, group: catalog.groups[0] },
    evidence: command.evidence, explanation: command.explanation,
  };
  const receiptUnsigned = { organization_id: 7, principal: "chief", kind: "expense_article_attribution", request_key: command.request_key,
    command, command_hash: await hash(command), result, result_digest: await hash(result) };
  const receipt = { ...receiptUnsigned, receipt_digest: await hash(receiptUnsigned) };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...contextUnsigned, digest: await hash(contextUnsigned) }) })
    .mockResolvedValueOnce({ ok: true, json: async () => receipt });
  vi.stubGlobal("fetch", fetchMock);

  await expect(dispatch(saved, "recover")).resolves.toMatchObject({ receipt });
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/accounting/organizations/7/expense-attributions/11111111-1111-4111-8111-111111111111",
    { cache: "no-store" },
  );
});
