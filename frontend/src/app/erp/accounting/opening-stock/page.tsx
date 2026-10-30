import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { AccountingOpeningStock } from "@/components/erp/accounting-opening-stock";

export default function OpeningStockPage() {
  return <AppShell crumbs={["ERP", "Бухгалтерия", "Начальные остатки"]}>
    <Link href="/erp/accounting" className="m-4 text-accent underline">Бухгалтерия</Link>
    <AccountingOpeningStock />
  </AppShell>;
}
