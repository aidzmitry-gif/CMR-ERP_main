"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

export type AccountingDestination = "expenses" | "seller-profiles" | "invoice-settlements" | "sale" | "inventory-issue" | "reconciliation" | "input-vat" | "reports" | "accounts" | "entry" | "bank" | "bank-import" | "payroll-accruals" | "payroll-statutory" | "setup" | "periods" | "inbox" | "import";
const actions: [AccountingDestination, string, string][] = [
  ["expenses", "Контроль расходов", "Вести группы, статьи и месячные черновики бюджета выбранного юрлица."],
  ["seller-profiles", "Реквизиты продавца", "Проверить реквизиты на дату и подтвердить новую версию для документов юрлица."],
  ["invoice-settlements", "Оплаты и возвраты счетов", "Сверить основания и подтвердить распределение банковской операции по точному счёту."],
  ["sale", "Продажа товаров", "Рассчитать выручку, НДС и стоимость партии одним пакетом."],
  ["inventory-issue", "Списание запасов", "Рассчитать стоимость партии и подтвердить бухгалтерское списание."],
  ["reconciliation", "Сверка ОСВ", "Сравнить два файла и получить протокол расхождений."],
  ["input-vat", "Входной НДС", "Проверить проводки счёта 18 и полноту их аналитики без определения вычета."],
  ["inbox", "Документы к проведению", "Проверить ожидающие документы и причины ошибок."],
  ["entry", "Бухгалтерская справка", "Подготовить ручную операцию или связанную корректировку."],
  ["bank", "Банковские операции", "Проверить и провести операцию по выписке."],
  ["bank-import", "Импорт выписки", "Привязать строку finance к юрлицу, проверить источник и провести её в книгу."],
  ["payroll-accruals", "Начисления зарплаты", "Импортировать проверенные валовые начисления с расшифровкой по сотрудникам и подразделениям."],
  ["payroll-statutory", "Удержания и взносы", "Импортировать проверенные суммы удержаний и взносов с обязательной квитанцией источника."],
  ["reports", "Журнал и отчёты", "ОСВ, проводки, баланс, прибыль и движение денег."],
  ["periods", "Контроль месяца", "Зафиксировать сверки и заблокировать проверенный период."],
  ["accounts", "Рабочие счета", "Просмотреть счета и обязательную аналитику юрлица."],
  ["import", "Начальные остатки", "Проверить файл остатков перед подтверждением переноса."],
  ["setup", "Политика и доступ", "Настроить книгу, версии счетов и права сотрудников."],
];

export function AccountingHome({ selected, pending, onOpen }: { selected: boolean; pending: number | null; onOpen: (destination: AccountingDestination) => void }) {
  return <section aria-label="Рабочее место бухгалтера" className="space-y-5">
    <div className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-xl font-semibold">Рабочее место бухгалтера</h2>
      <p className="mt-2 text-sm text-muted">{!selected ? "Выберите юридическое лицо для работы с его книгой." : pending === null ? "Состояние документов пока не получено. Проверьте загрузку книги." : `Не проведено документов по месяц окончания периода включительно: ${pending}.`}</p>
      <p className="mt-1 text-sm text-muted">Перед закрытием месяца проверьте полноту документов и сверки. Финансовые отчёты могут содержать предварительные данные.</p>
    </div>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{actions.map(([id, title, description]) => <div key={id} className="rounded-xl border border-line bg-surface p-4">
      <h3 className="font-semibold">{title}</h3><p className="my-3 text-sm text-muted">{description}</p>
      <Button variant="secondary" disabled={!selected && id !== "setup"} onClick={() => onOpen(id)} aria-label={`Открыть: ${title}`}>Открыть</Button>
    </div>)}</div>
    <section className="rounded-xl border border-line bg-surface p-5"><h3 className="font-semibold">Первичные документы и справочники</h3><p className="my-2 text-sm text-muted">Документы открываются в своих разделах. Перед проведением проверьте выбранное там юрлицо.</p><div className="flex flex-wrap gap-4">
      <Link className="text-accent underline" href="/erp/procurement/receipts">Накладные на поступление</Link>
      <Link className="text-accent underline" href="/erp/procurement/orders">Заказы поставщикам</Link>
      <Link className="text-accent underline" href="/erp/procurement/planning">План закупок</Link>
      <Link className="text-accent underline" href="/erp/spravochniki/accounts">Справочник плана счетов</Link>
    </div></section>
    <section className="rounded-xl border border-line p-5"><h3 className="font-semibold">Границы текущего модуля</h3><p className="mt-2 text-sm text-muted">Доступен импорт проверенных валовых начислений, удержаний и взносов; ставки и расчёт от оклада не угадываются, а нормативная сертификация и обязательная отчётность не выполняются. Регистры ЭСЧФ, налоговый календарь и отправка внешней отчётности требуют отдельных подтверждённых контуров.</p></section>
  </section>;
}
