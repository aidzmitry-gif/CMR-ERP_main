import { describe, expect, it } from "vitest";
import { clearRevision, pendingRevision, saveRevision } from "./production-output-cost-revision-journal";

describe("production output cost revision journal", () => {
  it("retains the exact UUID command for a same-principal retry and isolates another principal", () => {
    const values = new Map<string, string>();
    const store = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) };
    const pending = { org: "1", month: "2026-10", principal: "chief", command: { original_entry_id: 42, posting_date: "2026-10-31", request_evidence: "Late WIP", request_key: "550e8400-e29b-41d4-a716-446655440000", basis_digest: "a".repeat(64) } };
    saveRevision(store, pending);
    expect(pendingRevision(store, "1", "2026-10", "chief")).toEqual(pending);
    expect(pendingRevision(store, "1", "2026-10", "accountant")).toBeNull();
    clearRevision(store, pending);
    expect(pendingRevision(store, "1", "2026-10", "chief")).toBeNull();
  });

  it("rejects impossible dates and never removes a replacement command", () => {
    const values = new Map<string, string>();
    const store = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v), removeItem: (k: string) => values.delete(k) };
    const command = { original_entry_id: 42, posting_date: "2026-02-30", request_evidence: "Late WIP", request_key: "550e8400-e29b-41d4-a716-446655440000", basis_digest: "a".repeat(64) };
    expect(() => saveRevision(store, { org: "1", month: "2026-02", principal: "chief", command })).toThrow("повреждена");
    const first = { org: "1", month: "2026-02", principal: "chief", command: { ...command, posting_date: "2026-02-28" } };
    const replacement = { ...first, command: { ...first.command, request_key: "550e8400-e29b-41d4-a716-446655440001" } };
    saveRevision(store, first);
    values.set("production-output-cost-revision:[\"1\",\"2026-02\",\"chief\"]", JSON.stringify(replacement));
    clearRevision(store, first);
    expect(pendingRevision(store, "1", "2026-02", "chief")).toEqual(replacement);
  });
});
