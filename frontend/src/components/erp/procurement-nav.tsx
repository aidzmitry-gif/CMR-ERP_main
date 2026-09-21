import Link from "next/link";

export function ProcurementNav() {
  return <nav aria-label="Разделы закупок" className="flex flex-wrap gap-3 px-6 py-3 text-sm">
    <Link className="text-accent underline" href="/erp/procurement">Обзор и воронка</Link>
    <Link className="text-accent underline" href="/erp/procurement/planning">План закупок</Link>
    <Link className="text-accent underline" href="/erp/procurement/orders">Заказы и машины</Link>
    <Link className="text-accent underline" href="/erp/procurement/receipts">Накладные на поступление</Link>
    <Link className="text-accent underline" href="/erp/procurement/rfq">Запросы цен (RFQ)</Link>
    <Link className="text-accent underline" href="/erp/procurement/suppliers">Поставщики</Link>
    <Link className="text-accent underline" href="/erp/procurement/cost-calc">Калькулятор себестоимости</Link>
    <Link className="text-accent underline" href="/erp/procurement/additional-expenses">Дополнительные расходы</Link>
    <Link className="text-accent underline" href="/erp/procurement/claims">Претензии поставщикам</Link>
    <Link className="text-accent underline" href="/erp/procurement/ownership">Юрлица и связи</Link>
    <Link className="text-accent underline" href="/erp/procurement/company-documents">Документы юрлица</Link>
  </nav>;
}
