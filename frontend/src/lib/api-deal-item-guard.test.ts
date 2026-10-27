import { afterEach, expect, it, vi } from "vitest";

import { addDealItem, deleteDealItemIfCurrent, updateDealItemIfCurrent } from "./api";

afterEach(() => vi.unstubAllGlobals());

it("sends the same request key with a deal line command", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 201 });
  vi.stubGlobal("fetch", fetchMock);
  expect(await addDealItem("7", 3, 2, 15, "11111111-1111-4111-8111-111111111111")).toBe(true);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    sku_id: 3, qty: 2, unit_price: 15, request_key: "11111111-1111-4111-8111-111111111111",
  });
});

it("sends the shown row token for update and delete and reports conflicts", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 409 });
  vi.stubGlobal("fetch", fetchMock);
  const token = "a".repeat(64);
  expect(await updateDealItemIfCurrent(12, 3, 14, token)).toBe("conflict");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    qty: 3, unit_price: 14, expected_edit_token: token,
  });
  expect(await deleteDealItemIfCurrent(12, token)).toBe("conflict");
  expect(fetchMock.mock.calls[1][1].headers["If-Match"]).toBe(token);
});
