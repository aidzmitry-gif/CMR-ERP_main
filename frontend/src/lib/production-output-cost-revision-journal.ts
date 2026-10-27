export type RevisionCommand = {
  original_entry_id: number;
  posting_date: string;
  request_evidence: string;
  request_key: string;
  basis_digest: string;
};

export type PendingRevision = {
  org: string;
  month: string;
  principal: string;
  command: RevisionCommand;
};

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const key = (org: string, month: string, principal: string) =>
  `production-output-cost-revision:${JSON.stringify([org, month, principal])}`;

const isId = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
const isUuid = (value: unknown) =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

function isDateInMonth(value: unknown, month: string) {
  if (typeof value !== "string" || !new RegExp(`^${month}-\\d{2}$`).test(value)) return false;
  const [year, monthNumber, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, monthNumber - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === monthNumber - 1 && parsed.getUTCDate() === day;
}

function valid(value: unknown, org: string, month: string, principal: string): value is PendingRevision {
  const pending = value as PendingRevision;
  const command = pending?.command;
  return Boolean(
    pending && pending.org === org && pending.month === month && pending.principal === principal &&
    /^[1-9]\d*$/.test(org) && /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && principal.trim().length > 0 &&
    isId(command?.original_entry_id) && isDateInMonth(command?.posting_date, month) &&
    typeof command.request_evidence === "string" && command.request_evidence.trim().length > 0 &&
    command.request_evidence === command.request_evidence.trim() && isUuid(command.request_key) &&
    typeof command.basis_digest === "string" && /^[a-f0-9]{64}$/.test(command.basis_digest),
  );
}

export function pendingRevision(store: Store, org: string, month: string, principal: string): PendingRevision | null {
  const raw = store.getItem(key(org, month, principal));
  if (!raw) return null;
  const pending = JSON.parse(raw);
  if (!valid(pending, org, month, principal)) throw Error("Сохранённая корректировка выпуска повреждена.");
  return pending;
}

export function saveRevision(store: Store, pending: PendingRevision) {
  if (!valid(pending, pending.org, pending.month, pending.principal)) throw Error("Команда корректировки повреждена.");
  const old = pendingRevision(store, pending.org, pending.month, pending.principal);
  if (old && JSON.stringify(old) !== JSON.stringify(pending)) throw Error("Сначала завершите сохранённую корректировку выпуска.");
  store.setItem(key(pending.org, pending.month, pending.principal), JSON.stringify(pending));
}

export function clearRevision(store: Store, pending: PendingRevision) {
  const old = pendingRevision(store, pending.org, pending.month, pending.principal);
  if (old && JSON.stringify(old) === JSON.stringify(pending)) store.removeItem(key(pending.org, pending.month, pending.principal));
}
