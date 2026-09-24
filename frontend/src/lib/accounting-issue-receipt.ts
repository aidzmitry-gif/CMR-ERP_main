type PreparedCalculation = { kind?: string; digest: string; cost: { basis_digest: string } };

const positiveId = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0;

export function confirmedIssueReceipt(value: unknown, org: string, body: Record<string, unknown>,
                                      calculation: PreparedCalculation, sale: boolean): value is Record<string, unknown> {
  if (!value || typeof value !== "object") return false;
  const receipt = value as Record<string, unknown>;
  if (receipt.organization_id !== Number(org) || receipt.source !== body.source
      || receipt.source_version !== body.source_version || receipt.policy_id !== body.policy_id
      || receipt.posting_date !== body.posting_date || receipt.digest !== calculation.digest
      || receipt.document_date !== body.document_date || receipt.operation_date !== body.operation_date
      || receipt.operation !== (sale ? "inventory_sale" : "inventory_issue")) return false;
  if (calculation.kind === "quantity_only_receipt") {
    return !sale && receipt.kind === "quantity_only_receipt" && receipt.posted === true
      && positiveId(receipt.receipt_id) && positiveId(receipt.registration_token)
      && receipt.basis_digest === calculation.cost.basis_digest;
  }
  return positiveId(receipt.id);
}
