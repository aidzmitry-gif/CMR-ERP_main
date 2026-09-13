import { AccountingReceiptSource } from "./accounting-receipt-source";

export function AccountingSourceLink({ org, source, onPosted }: { org: string; source: string; onPosted?: () => void }) {
  const receipt = /^procurement:receipt:([1-9][0-9]*)$/.exec(source);
  if (receipt && /^[1-9][0-9]*$/.test(org)) return <AccountingReceiptSource key={`${org}:${receipt[1]}`} org={org} receiptId={receipt[1]} onPosted={onPosted} />;
  const act = /^wms:physical-shipment:([1-9][0-9]*):([a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12})$/.exec(source);
  if (act && act[1] === org) return <a href={`/api/accounting/organizations/${org}/shipments/${act[2]}/document`} target="_blank" rel="noreferrer" className="text-accent underline">Открыть внутренний акт отгрузки</a>;
  return null;
}
