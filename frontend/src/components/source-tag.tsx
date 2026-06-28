/**
 * SourceTag — единый провенанс-бейдж «откуда данные» (канон mdm-1c-data-provenance-ui).
 *
 * Помечает поля контрагента/номенклатуры/оплат как пришедшие из MDM-витрины (синхр. с 1С),
 * из 1С напрямую, из Bitrix или введённые в ERP. Один компонент на все экраны (карточка
 * сделки, drawer доски, leads), чтобы провенанс выглядел одинаково и правился в одном месте.
 *
 * `unp` опционален: пока DealDetail не несёт УНП с бэка — рендерим honest «УНП —»;
 * как только бэк начнёт отдавать `counterparty.unp`, достаточно прокинуть проп.
 */
const SOURCE_LABELS: Record<string, string> = {
  "mdm/1c": "MDM / 1С",
  mdm: "MDM",
  "1c": "1С",
  bitrix: "Bitrix",
  erp: "ERP",
  // провенанс мастер-входа SKU (own ∨ group ∨ от кода ТН ВЭД) — per-field бейдж на карточке (REF3-4)
  own: "ERP",
  group: "группы",
  tnved: "ТН ВЭД",
};

export function SourceTag({
  entity,
  source,
  unp,
}: {
  entity?: string; // класс данных («Номенклатура»); опускается для per-field провенанса
  source: string;
  unp?: string | null;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
      <span className="rounded-md bg-sunken px-1.5 py-0.5 font-semibold text-muted">
        {entity ? `${entity} · ` : ""}из {SOURCE_LABELS[source] ?? source}
      </span>
      {unp && <span className="text-faint">УНП {unp}</span>}
    </span>
  );
}
