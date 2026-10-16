import { inventoryErrorMessage } from "@/lib/wms-inventory";

export function WmsInventoryPageError({ error, href }: { error: unknown; href: string }) {
  return <div className="p-6"><p role="alert" className="text-sm text-red-600">{inventoryErrorMessage(error)}</p>
    <a href={href} className="mt-3 inline-block text-sm underline">Повторить загрузку</a></div>;
}

export function inventoryOrganizationParam(value?: string): number | null {
  if (value === undefined || value === "") return null;
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) <= 0) throw new Error("Некорректный фильтр юрлица.");
  return Number(value);
}
