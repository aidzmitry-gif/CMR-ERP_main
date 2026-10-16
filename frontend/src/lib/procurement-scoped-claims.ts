import type { Claim, ClaimStatus } from "@/lib/procurement-claims";

export type ScopedClaim = Omit<Claim, "amount_byn"> & { amount_byn: string | null };
export type OwnedClaim = {
  organization_id: number;
  order_id: number | null;
  claim: ScopedClaim;
  ownership: { actor: string; created_at: string; evidence: string };
  source_snapshot?: ClaimSourceSnapshot;
};
export type ClaimPage = { organization_id: number; items: OwnedClaim[];
  next_after_id: number | null; unassigned_claims_excluded: true };
export type ClaimCommand = { claim_key: string; supplier_id: number; supplier: string;
  supplier_unp: string; order_id: number | null; item: string; reason: string;
  claim_type: string; qty_affected: number; amount_byn: string | null;
  ownership_evidence: string };
export type ClaimResolution = { edit_key: string; expected_status: "open";
  status: Exclude<ClaimStatus, "open">; resolution: string };
export type ClaimOrder = { id: number; number: string; supplier: string };
export type ClaimHistory = { organization_id: number; claim_id: number;
  created: { actor: string; created_at: string; evidence: string; snapshot: ScopedClaim;
    source_snapshot: ClaimSourceSnapshot | null };
  edits: { actor: string; created_at: string; before: { status: string; resolution: string };
    after: { status: string; resolution: string } }[] };
export type ClaimSourceSnapshot = { id: number; source: "production"; entity_ref: string;
  item: string; reason: string; order_code: string; status: "open";
  supplier_id: number | null; supplier: string; amount_byn: string | null };
export type ClaimPreviewFacts = { entity_ref: string; item: string; reason: string; order_code: string };
export type ClaimPreview = { organization_id: number; claim_id: number;
  source_snapshot: ClaimSourceSnapshot; source_digest: string };
export type ClaimBindCommand = { claim_key: string; entity_ref: string; expected_digest: string;
  supplier_id: number; supplier: string; supplier_unp: string; order_id: number | null;
  ownership_evidence: string };

const validId = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const prefix = (org: number) => `/api/procurement/organizations/${org}`;

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...init });
  if (!response.ok) throw new Error(`Закупки не подтвердили операцию (${response.status})`);
  return response.json() as Promise<T>;
}

function owned(value: OwnedClaim, org: number, claimId?: number): OwnedClaim {
  if (!value || value.organization_id !== org || !value.claim || !validId(value.claim.id)
      || (claimId !== undefined && value.claim.id !== claimId)
      || !value.ownership || typeof value.ownership.actor !== "string")
    throw new Error("Ответ претензии не соответствует выбранному юрлицу");
  return value;
}

export async function listClaims(org: number, afterId = 0): Promise<ClaimPage> {
  if (!validId(org) || !Number.isSafeInteger(afterId) || afterId < 0) throw new Error("Выберите юрлицо");
  const result = await request<ClaimPage>(`${prefix(org)}/claims?after_id=${afterId}`);
  if (result.organization_id !== org || !Array.isArray(result.items)
      || result.items.length > 50 || result.unassigned_claims_excluded !== true
      || result.items.some(row => { try { owned(row, org); return false; } catch { return true; } }))
    throw new Error("Ответ претензий не соответствует выбранному юрлицу");
  return result;
}

export async function createClaim(org: number, principal: string, command: ClaimCommand): Promise<OwnedClaim> {
  if (!validId(org) || !principal || !validId(command.supplier_id)) throw new Error("Выберите юрлицо и поставщика");
  const result = await request<OwnedClaim>(`${prefix(org)}/claims`, { method: "POST",
    headers: { "Content-Type": "application/json", "X-Expected-Principal": principal },
    body: JSON.stringify(command) });
  return owned(result, org);
}

export async function resolveClaim(org: number, claimId: number, principal: string,
                                   command: ClaimResolution): Promise<OwnedClaim> {
  if (!validId(org) || !validId(claimId) || !principal) throw new Error("Выберите претензию");
  const result = await request<OwnedClaim>(`${prefix(org)}/claims/${claimId}/resolve`, { method: "POST",
    headers: { "Content-Type": "application/json", "X-Expected-Principal": principal },
    body: JSON.stringify(command) });
  return owned(result, org, claimId);
}

export async function claimHistory(org: number, claimId: number): Promise<ClaimHistory> {
  if (!validId(org) || !validId(claimId)) throw new Error("Выберите претензию");
  const result = await request<ClaimHistory>(`${prefix(org)}/claims/${claimId}/history`);
  if (result.organization_id !== org || result.claim_id !== claimId || !Array.isArray(result.edits))
    throw new Error("История не соответствует выбранному юрлицу");
  return result;
}

export async function searchClaimOrders(org: number, q: string): Promise<ClaimOrder[]> {
  if (!validId(org)) throw new Error("Выберите юрлицо");
  const result = await request<{ organization_id: number; items: ClaimOrder[] }>(
    `${prefix(org)}/owned-sources?kind=order&q=${encodeURIComponent(q.trim())}`);
  if (result.organization_id !== org || !Array.isArray(result.items)
      || result.items.some(row => !validId(row.id) || typeof row.number !== "string"))
    throw new Error("Заказы не соответствуют выбранному юрлицу");
  return result.items;
}

export async function previewUnassignedClaim(org: number, principal: string,
                                             facts: ClaimPreviewFacts): Promise<ClaimPreview> {
  if (!validId(org) || !principal) throw new Error("Выберите юрлицо");
  const result = await request<ClaimPreview>(`${prefix(org)}/unassigned-claim-preview`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": principal },
    body: JSON.stringify(facts),
  });
  if (result.organization_id !== org || !validId(result.claim_id)
      || result.source_snapshot?.id !== result.claim_id
      || result.source_snapshot?.source !== "production"
      || result.source_snapshot?.status !== "open"
      || result.source_snapshot?.supplier_id !== null
      || result.source_snapshot?.supplier !== ""
      || result.source_snapshot?.entity_ref !== facts.entity_ref
      || result.source_snapshot?.item !== facts.item
      || result.source_snapshot?.reason !== facts.reason
      || result.source_snapshot?.order_code !== facts.order_code
      || !/^[0-9a-f]{64}$/.test(result.source_digest))
    throw new Error("Снимок ОТК не соответствует выбранному юрлицу и основанию");
  return result;
}

export async function bindUnassignedClaim(org: number, claimId: number, principal: string,
                                          command: ClaimBindCommand): Promise<OwnedClaim> {
  if (!validId(org) || !validId(claimId) || !principal || !validId(command.supplier_id))
    throw new Error("Выберите юрлицо, претензию и поставщика");
  const result = await request<OwnedClaim>(`${prefix(org)}/claims/${claimId}/bind`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-Expected-Principal": principal },
    body: JSON.stringify(command),
  });
  return owned(result, org, claimId);
}
