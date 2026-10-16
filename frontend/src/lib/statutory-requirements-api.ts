export type RequirementKind = "form" | "rate";
export type StatutoryRequirement = {
  requirement_id: number; organization_id: number; kind: RequirementKind; code: string; title: string;
  effective_from: string; revision: number; source_reference: string; evidence: string;
  form_version: string | null; electronic_format_version: string | null;
  rate_value: string | null; rate_unit: string | null; rate_basis: string | null;
  request_key: string; digest: string; actor: string;
};
export type StatutoryRequirementRequest = {
  request_key: string; kind: RequirementKind; code: string; title: string; effective_from: string;
  source_reference: string; evidence: string; form_version: string | null; electronic_format_version: string | null;
  rate_value: string | null; rate_unit: string | null; rate_basis: string | null;
};
export class StatutoryRequirementError extends Error { constructor(message: string, public status?: number) { super(message); } }

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const id = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const text = (value: unknown, min = 1, max = 2000): value is string => typeof value === "string" && value === value.trim() && value.length >= min && value.length <= max && !value.includes("\0");
const orgId = (value: string) => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value));
const period = (value: string) => /^\d{4}-\d{2}$/.test(value) && new Date(`${value}-01T00:00:00Z`).toISOString().slice(0, 7) === value;
const date = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-01$/.test(value) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const uuid = (value: unknown) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const decimal = (value: unknown) => typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value);
function canonicalDecimal(value: string): string {
  const [whole, fraction = ""] = value.split(".");
  const integer = whole.replace(/^0+(?=\d)/, "");
  const tail = fraction.replace(/0+$/, "");
  return tail ? `${integer}.${tail}` : integer;
}
function invalid(): never { throw new StatutoryRequirementError("Некорректный ответ каталога или другое юрлицо. Результат не подтверждён."); }
function base(org: string) { if (!orgId(org)) invalid(); return `/api/accounting/organizations/${org}`; }

function row(value: unknown, org: string, month: string): StatutoryRequirement {
  const effective = object(value) ? value.effective_from : undefined;
  if (!object(value) || value.organization_id !== Number(org) || !id(value.requirement_id)
    || !["form", "rate"].includes(String(value.kind)) || !text(value.code, 1, 120) || !text(value.title, 1, 500)
    || !date(effective) || effective > `${month}-01` || !id(value.revision)
    || !text(value.source_reference, 1, 1000) || !text(value.evidence, 10, 2000) || !uuid(value.request_key)
    || !digest(value.digest) || !text(value.actor, 1, 200)) invalid();
  const form = value.form_version, electronic = value.electronic_format_version;
  const rate = value.rate_value, unit = value.rate_unit, basis = value.rate_basis;
  if (value.kind === "form") {
    if (!text(form, 1, 120) || !text(electronic, 1, 120) || rate !== null || unit !== null || basis !== null) invalid();
  } else if (!decimal(rate) || !text(unit, 1, 120) || !text(basis, 1, 500) || form !== null || electronic !== null) invalid();
  return value as StatutoryRequirement;
}

async function request(url: string, body?: StatutoryRequirementRequest): Promise<unknown> {
  let response: Response;
  try { response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); }
  catch { throw new StatutoryRequirementError(body ? "Результат сохранения неизвестен. Повторите сохранённый запрос." : "Каталог не загружен: сеть недоступна."); }
  if (!response.ok) throw new StatutoryRequirementError(`${response.status}: ${response.status === 403 ? "Недостаточно прав бухгалтера." : "Сервер не подтвердил результат."}`, response.status);
  try { return await response.json(); } catch { invalid(); }
}

export function statutoryRequirementKey(): string {
  const key = globalThis.crypto?.randomUUID?.();
  if (!uuid(key)) throw new StatutoryRequirementError("Не удалось безопасно создать ключ запроса. Сохранение не отправлено.");
  return key;
}

export function validStatutoryRequirement(body: StatutoryRequirementRequest): boolean {
  const common = uuid(body.request_key) && ["form", "rate"].includes(body.kind) && text(body.code, 1, 120)
    && text(body.title, 1, 500) && date(body.effective_from) && text(body.source_reference, 1, 1000) && text(body.evidence, 10, 2000);
  return common && (body.kind === "form"
    ? text(body.form_version, 1, 120) && text(body.electronic_format_version, 1, 120)
      && body.rate_value === null && body.rate_unit === null && body.rate_basis === null
    : decimal(body.rate_value) && text(body.rate_unit, 1, 120) && text(body.rate_basis, 1, 500)
      && body.form_version === null && body.electronic_format_version === null);
}

export async function fetchStatutoryRequirements(org: string, month: string): Promise<StatutoryRequirement[]> {
  if (!period(month)) invalid();
  const value = await request(`${base(org)}/periods/${month}/statutory-requirements`);
  if (!Array.isArray(value) || value.length > 500) invalid();
  const rows = value.map((item) => row(item, org, month));
  if (new Set(rows.map((item) => `${item.kind}/${item.code}`)).size !== rows.length) invalid();
  return rows;
}

export async function createStatutoryRequirement(org: string, body: StatutoryRequirementRequest) {
  if (!validStatutoryRequirement(body)) invalid();
  const payload: StatutoryRequirementRequest = { ...body };
  const saved = row(await request(`${base(org)}/statutory-requirements`, payload), org, payload.effective_from.slice(0, 7));
  if (saved.request_key !== payload.request_key || saved.kind !== payload.kind || saved.code !== payload.code
    || saved.title !== payload.title || saved.effective_from !== payload.effective_from
    || saved.source_reference !== payload.source_reference || saved.evidence !== payload.evidence
    || saved.form_version !== payload.form_version || saved.electronic_format_version !== payload.electronic_format_version
    || (saved.rate_value !== null && payload.rate_value !== null && canonicalDecimal(saved.rate_value) !== canonicalDecimal(payload.rate_value))
    || (saved.rate_value === null) !== (payload.rate_value === null)
    || saved.rate_unit !== payload.rate_unit || saved.rate_basis !== payload.rate_basis) invalid();
  return saved;
}
