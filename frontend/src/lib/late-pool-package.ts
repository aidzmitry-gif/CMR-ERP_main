/** Validate the distinct signed V3 pool package before it can be confirmed or shown. */
export type PoolCostLine = { account: string; side: "debit" | "credit"; amount: string; dimensions: Record<string, string> };
export type PoolOutput = { output_entry_id: number; amount_byn: string; lines: PoolCostLine[] };

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const id = (value: unknown) => Number.isSafeInteger(value) && (value as number) > 0;
function cents(value: unknown): bigint {
  if (typeof value !== "string" || !/^-?\d{1,18}\.\d{2}$/.test(value)) throw new Error("Некорректная сумма V3-пакета.");
  const sign = value.startsWith("-") ? -1n : 1n, [whole, fraction] = (value.startsWith("-") ? value.slice(1) : value).split(".");
  return sign * (BigInt(whole) * 100n + BigInt(fraction));
}
function money(value: bigint): string {
  const sign = value < 0n ? "-" : "", absolute = value < 0n ? -value : value;
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (record(value)) return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
function normalized(value: unknown) {
  if (!record(value) || !record(value.allocation) || !record(value.accounts) || !Array.isArray(value.accounts.excluded_costs)) {
    throw new Error("Команда V3-пакета не подтверждена.");
  }
  const allocation = value.allocation, accounts = value.accounts;
  const excluded = accounts.excluded_costs;
  if (!Array.isArray(excluded)) throw new Error("Некорректная исключённая сумма V3.");
  const decimal = (item: unknown) => {
    if (typeof item !== "string" || !/^\d{1,18}(?:\.\d{1,2})?$/.test(item)) throw new Error("Некорректная сумма команды V3.");
    const [whole, fraction = ""] = item.split(".");
    return `${BigInt(whole)}.${fraction.padEnd(2, "0")}`;
  };
  return { allocation: { ...allocation, conversion: allocation.conversion ?? null,
    capitalizable_amount_byn: decimal(allocation.capitalizable_amount_byn), excluded_amount_byn: decimal(allocation.excluded_amount_byn) },
    accounts: { ...accounts, excluded_costs: excluded.map((row: unknown) => {
      if (!record(row)) throw new Error("Некорректная исключённая сумма V3.");
      return { ...row, amount_byn: decimal(row.amount_byn) };
    }) } };
}

/** The server selects V3 outputs; the browser can only verify the returned immutable selection. */
export function checkedPoolOutputs(value: unknown, requested?: Record<string, unknown>): PoolOutput[] {
  if (!record(value) || !record(value.command) || value.command.command_version !== 3
    || !Array.isArray(value.command.material_outputs) || !Array.isArray(value.outputs) || value.outputs.length > 100
    || value.outputs.length !== value.command.material_outputs.length || !Array.isArray(value.wip_origins)
    || !record(value.posting) || !Array.isArray(value.posting.lines)) throw new Error("Неполный V3-пакет распределения.");
  if (requested) {
    if (requested.command_version !== 3 || !Array.isArray(requested.material_outputs) || requested.material_outputs.length !== 0
      || stable(normalized(value.command)) !== stable(normalized(requested))) {
      throw new Error("V3-расчёт относится к другой команде расходов.");
    }
  }
  const selected = value.command.material_outputs;
  const outputs = value.outputs.map((row, index) => {
    const selection = selected[index];
    if (!record(row) || !record(selection) || !id(row.output_entry_id) || selection.output_entry_id !== row.output_entry_id
      || selection.amount_byn !== row.amount_byn || cents(row.amount_byn) === 0n
      || !record(row.prospective_evidence) || !Array.isArray(row.prospective_evidence.matrix)
      || row.prospective_evidence.matrix.length === 0) throw new Error("Состав V3-корректировок не подтверждён.");
    let debit = 0n, credit = 0n, wipCredit = 0n;
    const lines = row.prospective_evidence.matrix.map(line => {
      if (!record(line) || typeof line.account !== "string" || !/^\d+(?:\.\d+)*$/.test(line.account)
        || !["debit", "credit"].includes(String(line.side)) || !record(line.dimensions)
        || Object.values(line.dimensions).some(item => typeof item !== "string")) throw new Error("Некорректная V3-проводка выпуска.");
      const amount = cents(line.amount);
      if (amount <= 0n) throw new Error("Некорректная сумма V3-корректировки выпуска.");
      if (line.side === "debit") debit += amount; else credit += amount;
      if (line.account.split(".")[0] === "20") wipCredit += line.side === "credit" ? amount : -amount;
      return { account: line.account, side: line.side as "debit" | "credit", amount: money(amount), dimensions: line.dimensions as Record<string, string> };
    });
    if (debit !== credit || wipCredit !== cents(row.amount_byn)) throw new Error("V3-корректировка выпуска не сходится с затратами.");
    return { output_entry_id: row.output_entry_id as number, amount_byn: row.amount_byn as string, lines };
  });
  if (new Set(outputs.map(row => row.output_entry_id)).size !== outputs.length) throw new Error("Выпуск повторяется в V3-пакете.");
  const allocated = outputs.reduce((sum, row) => sum + cents(row.amount_byn), 0n) + value.wip_origins.reduce((sum: bigint, row) => {
    if (!record(row) || !id(row.entry_id) || !id(row.order_id)) throw new Error("НЗП V3-пакета не подтверждено.");
    return sum + cents(row.amount_byn);
  }, 0n);
  const wip = value.posting.lines.reduce((sum: bigint, row) => {
    if (!record(row) || typeof row.account !== "string" || !["debit", "credit"].includes(String(row.side))) return sum;
    const amount = cents(row.amount);
    return row.account.split(".")[0] === "20" ? sum + (row.side === "debit" ? amount : -amount) : sum;
  }, 0n);
  if (wip !== allocated) throw new Error("V3-пакет не распределяет все производственные затраты.");
  return outputs;
}

/** V3 history must preserve the exact inventory-value links stored with the package. */
export function checkedPoolReceipt(value: unknown): PoolOutput[] {
  if (!record(value) || !record(value.preview) || !id(value.entry_id) || !Array.isArray(value.inventory_value_links)) {
    throw new Error("Исторический V3-пакет неполный.");
  }
  const outputs = checkedPoolOutputs(value.preview);
  const calculation = value.preview.calculation;
  if (!record(calculation) || !Array.isArray(calculation.destinations)) throw new Error("Исторический расчёт V3-пакета неполный.");
  const inventory = calculation.destinations.filter(row => record(row) && row.kind === "inventory" && cents(row.delta_byn) !== 0n);
  const links = value.inventory_value_links;
  if (links.length !== inventory.length || links.length > 10000
    || new Set(links.map(row => record(row) ? row.value_line_id : null)).size !== links.length
    || links.some(row => !record(row) || row.value_entry_id !== value.entry_id || !id(row.value_line_id)
      || !id(row.acquisition_entry_id) || !id(row.acquisition_line_id))) {
    throw new Error("Связи стоимости запасов V3-пакета не подтверждены.");
  }
  return outputs;
}
