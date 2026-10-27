/** Validate every output adjustment before offering a material-cost command. */
export type MaterialCostLine = { account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> };
export type MaterialOutput = { output_entry_id: number; amount_byn: string; lines: MaterialCostLine[] };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
function cents(value: unknown): bigint {
  const text = typeof value === "number" && Number.isSafeInteger(value) ? String(value) : value;
  if (typeof text !== "string" || !/^\d{1,18}(?:\.\d{1,2})?$/.test(text)) throw new Error("Некорректная сумма корректировки выпуска.");
  const [whole, fraction = ""] = text.split(".");
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
}
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (record(value)) return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${stable(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
function normalizedCommand(value: Record<string, unknown>) {
  if (!record(value.allocation) || !record(value.accounts) || !Array.isArray(value.accounts.excluded_costs)) throw new Error("Команда расходов не подтверждена.");
  const allocation = value.allocation;
  return { allocation: { ...allocation, conversion: allocation.conversion ?? null,
    capitalizable_amount_byn: String(cents(allocation.capitalizable_amount_byn)),
    excluded_amount_byn: String(cents(allocation.excluded_amount_byn)) },
    accounts: { ...value.accounts, excluded_costs: value.accounts.excluded_costs.map(row => {
      if (!record(row)) throw new Error("Некорректная исключённая сумма.");
      return { ...row, amount_byn: String(cents(row.amount_byn)) };
    }) } };
}
export function checkedMaterialOutputs(value: unknown, requested?: Record<string, unknown>): MaterialOutput[] {
  if (!record(value) || !record(value.command) || value.command.command_version !== 2
    || !Array.isArray(value.command.material_outputs) || !Array.isArray(value.outputs) || value.outputs.length > 100
    || value.outputs.length !== value.command.material_outputs.length || !Array.isArray(value.wip_origins)
    || !record(value.posting) || !Array.isArray(value.posting.lines)) throw new Error("Неполный производственный пакет.");
  if (requested && stable(normalizedCommand(value.command)) !== stable(normalizedCommand(requested))) throw new Error("Расчёт относится к другой команде расходов.");
  const selections = value.command.material_outputs;
  const outputs = value.outputs.map((row, index) => {
    const selected = selections[index];
    if (!record(row) || !id(row.output_entry_id) || !record(selected) || selected.output_entry_id !== row.output_entry_id
      || selected.amount_byn !== row.amount_byn || cents(row.amount_byn) <= 0n
      || !record(row.prospective_evidence) || !Array.isArray(row.prospective_evidence.matrix)
      || row.prospective_evidence.matrix.length === 0) throw new Error("Состав выпусков не подтверждён.");
    let debit = 0n, credit = 0n, wipCredit = 0n;
    const lines = row.prospective_evidence.matrix.map(line => {
      if (!record(line) || typeof line.account !== "string" || !/^\d+(?:\.\d+)*$/.test(line.account)
        || !["debit", "credit"].includes(String(line.side)) || !record(line.dimensions)
        || Object.values(line.dimensions).some(item => typeof item !== "string")) throw new Error("Некорректная проводка выпуска.");
      const amount = cents(line.amount);
      if (amount <= 0n) throw new Error("Некорректная сумма корректировки выпуска.");
      if (line.side === "debit") debit += amount; else credit += amount;
      if (line.account.split(".")[0] === "20") wipCredit += line.side === "credit" ? amount : -amount;
      return { ...line, amount: `${amount / 100n}.${String(amount % 100n).padStart(2, "0")}` } as MaterialCostLine;
    });
    if (debit !== credit || wipCredit !== cents(row.amount_byn)) throw new Error("Корректировка выпуска не сходится с дополнительными расходами.");
    return { output_entry_id: row.output_entry_id as number, amount_byn: row.amount_byn as string, lines };
  });
  if (new Set(outputs.map(row => row.output_entry_id)).size !== outputs.length) throw new Error("Выпуск повторяется в пакете.");
  const allocated = outputs.reduce((sum, row) => sum + cents(row.amount_byn), 0n) + value.wip_origins.reduce((sum: bigint, row) => {
    if (!record(row)) throw new Error("НЗП не подтверждено.");
    return sum + cents(row.amount_byn);
  }, 0n);
  const wip = value.posting.lines.reduce((sum: bigint, line) => record(line) && line.side === "debit"
    && String(line.account).split(".")[0] === "20" ? sum + cents(line.amount) : sum, 0n);
  if (wip <= 0n || wip !== allocated) throw new Error("Не все затраты производства распределены.");
  return outputs;
}
