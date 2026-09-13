/** One exact pending command per company/principal in this browser tab. */
export type ExpenseCommand = { path: string; method: "POST" | "PUT"; body: string; principal: string };
type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const key = (org: string, principal: string) => `additional-expense-command:${JSON.stringify([org, principal])}`;

function checked(value: unknown, org: string, principal: string): ExpenseCommand {
  if (!value || typeof value !== "object") throw new Error("Повреждён сохранённый запрос расхода.");
  const item = value as ExpenseCommand;
  const base = `/organizations/${org}/additional-expenses`;
  if (item.principal !== principal || typeof item.body !== "string"
    || !((item.method === "POST" && item.path === base)
      || (item.method === "PUT" && typeof item.path === "string" && item.path.startsWith(`${base}/`) && /^[1-9][0-9]*$/.test(item.path.slice(base.length + 1))))) {
    throw new Error("Сохранённый запрос относится к другому документу или пользователю.");
  }
  const body = JSON.parse(item.body);
  if (!body || typeof body !== "object" || !body.document || typeof body.document !== "object"
    || !Array.isArray(body.document.receipt_lines) || !body.document.receipt_lines.length
    || (item.method === "POST" && (typeof body.key !== "string" || !/^[0-9a-f-]{36}$/.test(body.key)))
    || (item.method === "PUT" && (!Number.isSafeInteger(body.expected_version) || body.expected_version < 1))) {
    throw new Error("Повреждено содержимое сохранённого запроса.");
  }
  const fields = ["invoice_reference", "supplier", "contract", "document_date", "operation_date", "currency", "amount", "explanation"];
  if (fields.some(field => typeof body.document[field] !== "string")
    || Object.keys(body.document).some(field => ![...fields, "receipt_lines"].includes(field))
    || body.document.receipt_lines.length > 300
    || body.document.receipt_lines.some((line: Record<string, unknown>) => !line || typeof line !== "object"
      || Object.keys(line).length !== 3 || ["receipt_id", "version", "line_number"].some(field => !Number.isSafeInteger(line[field]) || (line[field] as number) < 1))) {
    throw new Error("Повреждены реквизиты или строки сохранённого запроса.");
  }
  return item;
}

export function pendingExpense(store: Store, org: string, principal: string): ExpenseCommand | null {
  const raw = store.getItem(key(org, principal));
  return raw === null ? null : checked(JSON.parse(raw), org, principal);
}
export function rememberExpense(store: Store, org: string, command: ExpenseCommand) {
  checked(command, org, command.principal);
  const current = pendingExpense(store, org, command.principal);
  if (current && JSON.stringify(current) !== JSON.stringify(command)) throw new Error("Сначала завершите предыдущий запрос расхода.");
  const value = JSON.stringify(command);
  store.setItem(key(org, command.principal), value);
  if (store.getItem(key(org, command.principal)) !== value) throw new Error("Не удалось сохранить запрос для восстановления. Отправка остановлена.");
}
export function forgetExpense(store: Store, org: string, command: ExpenseCommand) {
  const current = pendingExpense(store, org, command.principal);
  if (!current || JSON.stringify(current) !== JSON.stringify(command)) throw new Error("Сохранённый запрос изменился. Проверьте документ после обновления страницы.");
  store.removeItem(key(org, command.principal));
  if (store.getItem(key(org, command.principal)) !== null) throw new Error("Не удалось завершить сохранённый запрос.");
}
