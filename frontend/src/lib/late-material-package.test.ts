import { expect, it } from "vitest";
import { checkedMaterialOutputs } from "./late-material-package";

const command = { command_version: 2, material_outputs: [{ output_entry_id: 12, amount_byn: "2.00" }] };
const data = { command, posting: { lines: [{ account: "20", side: "debit", amount: "2.00" }] }, wip_origins: [],
  outputs: [{ output_entry_id: 12, amount_byn: "2.00", prospective_evidence: { matrix: [
    { account: "43", side: "debit", amount: "1.00", dimensions: { lot: "A" } },
    { account: "90.4", side: "debit", amount: "1.00", dimensions: {} },
    { account: "20", side: "credit", amount: "2.00", dimensions: { order: "ORDER" } },
  ] } }] };
it("keeps both inventory and sold-output costs in the reviewed matrix", () => {
  expect(checkedMaterialOutputs(data)[0].lines.map(row => row.account)).toEqual(["43", "90.4", "20"]);
});
it.each(["missing", "unbalanced", "unallocated"])("rejects incomplete material preview: %s", attack => {
  const forged = structuredClone(data);
  if (attack === "missing") forged.outputs = [];
  if (attack === "unbalanced") forged.outputs[0].prospective_evidence.matrix[0].amount = "0.99";
  if (attack === "unallocated") forged.posting.lines[0].amount = "3.00";
  expect(() => checkedMaterialOutputs(forged)).toThrow();
});

it("allows cent redistribution between destinations while net WIP credit equals added cost", () => {
  const revised = structuredClone(data);
  revised.posting.lines[0].amount = "0.01";
  revised.command.material_outputs[0].amount_byn = "0.01";
  revised.outputs[0].amount_byn = "0.01";
  revised.outputs[0].prospective_evidence.matrix = [
    { account: "43", side: "debit", amount: "0.03", dimensions: { lot: "A" } },
    { account: "43", side: "credit", amount: "0.02", dimensions: { lot: "B" } },
    { account: "20", side: "credit", amount: "0.01", dimensions: { order: "ORDER" } },
  ];
  expect(checkedMaterialOutputs(revised)[0].lines).toHaveLength(3);
});
