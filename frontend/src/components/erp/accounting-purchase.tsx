"use client";

import Link from "next/link";

// Historical direct purchase postings remain readable in the accounting journal.
// Every new incoming invoice is created as a Procurement primary document.
export function AccountingPurchase({ org }: { org: string }) {
  const book = /^[1-9]\d*$/.test(org) && Number.isSafeInteger(Number(org)) ? `?org=${org}` : "";
  return <section className="space-y-3 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Накладные на поступление</h2>
    <p>Новые накладные оформляются в закупках. После сохранения документа бухгалтер рассчитывает и подтверждает его проводки из карточки накладной.</p>
    <Link href={`/erp/procurement/receipts${book}`} className="text-accent underline">Открыть накладные в закупках</Link>
  </section>;
}
