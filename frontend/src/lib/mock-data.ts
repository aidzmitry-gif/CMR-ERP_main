import { STAGE_BY_ID } from "@/lib/sales-stages";
import type { Chat, DealDetail, FunnelTotal, Kpi, Stage } from "@/lib/types";

// Демо-данные прототипа (как на макете). Подставляются вместо реального API.

export const KPIS: Kpi[] = [
  { id: "key", label: "Звонки ключевым клиентам", value: 24, target: 40, percent: 60, icon: "phone-key", tone: "blue" },
  { id: "all", label: "Всего звонков", value: 58, target: 100, percent: 58, icon: "phone", tone: "indigo" },
  { id: "ship", label: "План по сумме отгрузки", value: 5_200_000, target: 8_000_000, percent: 65, money: true, icon: "ruble", tone: "green" },
  { id: "cold", label: "Холодные звонки", value: 32, target: 60, percent: 53, icon: "snow", tone: "cyan" },
  { id: "req", label: "Обработка заявок", value: 18, target: 30, percent: 60, icon: "doc", tone: "slate" },
];

export const STAGES: Stage[] = [
  {
    ...STAGE_BY_ID.new,
    count: 125,
    sum: 8_450_000,
    deals: [
      { id: "0156n", number: "CRM-2024-0156", company: "ООО МеталлПром", description: "Поставка металлопроката", amount: 850_000, priority: "Высокий", nextStep: "Звонок", owner: "Иванов И.И.", date: "12.05.2024", starred: true },
      { id: "0157", number: "CRM-2024-0157", company: "АО СтройКомплект", description: "Комплектующие для оборудования", amount: 1_250_000, priority: "Средний", nextStep: "Встреча", owner: "Петров П.П.", date: "12.05.2024" },
      { id: "0158", number: "CRM-2024-0158", company: "ООО ТехноСервис", description: "Сервисное обслуживание", amount: 320_000, priority: "Низкий", nextStep: "КП", owner: "Сидоров С.С.", date: "11.05.2024" },
    ],
  },
  {
    ...STAGE_BY_ID.qual,
    count: 68,
    sum: 12_300_000,
    deals: [
      { id: "0132", number: "CRM-2024-0132", company: "ООО Завод Прогресс", description: "Поставка оборудования", amount: 2_500_000, priority: "Высокий", nextStep: "КП", owner: "Иванов И.И.", date: "12.05.2024", starred: true },
      { id: "0133", number: "CRM-2024-0133", company: "ПАО Энергия", description: "Модернизация линии", amount: 3_200_000, priority: "Средний", nextStep: "Встреча", owner: "Петров П.П.", date: "11.05.2024" },
      { id: "0134", number: "CRM-2024-0134", company: "ООО КомплектСнаб", description: "Расходные материалы", amount: 480_000, priority: "Низкий", nextStep: "КП", owner: "Иванов И.И.", date: "11.05.2024" },
    ],
  },
  {
    ...STAGE_BY_ID.has_price,
    count: 35,
    sum: 9_750_000,
    deals: [
      { id: "0156", number: "CRM-2024-0156", company: "ООО АльфаМеталл", description: "Поставка металлопроката", amount: 1_750_000, priority: "Высокий", owner: "Иванов П.П.", date: "12.05.2024", starred: true, todo: "Согласовать КП с клиентом", actionTime: "12.05.2024", actionDate: "12.05.2024", itemsLabel: "Металлопрокат", itemsCount: 12 },
      { id: "0135", number: "CRM-2024-0135", company: "АО Машиностроитель", description: "Изготовление деталей", amount: 2_900_000, priority: "Средний", nextStep: "Согласование", owner: "Иванов И.И.", date: "11.05.2024" },
    ],
  },
  {
    ...STAGE_BY_ID.contract,
    count: 18,
    sum: 6_200_000,
    deals: [
      { id: "0121", number: "CRM-2024-0121", company: "ПАО ХимПром", description: "Комплексная поставка", amount: 4_200_000, priority: "Высокий", nextStep: "Договор", owner: "Сидоров С.С.", date: "12.05.2024", starred: true },
      { id: "0122", number: "CRM-2024-0122", company: "ООО СтройИнвест", description: "Строительные материалы", amount: 1_850_000, priority: "Средний", nextStep: "Согласование", owner: "Иванов И.И.", date: "11.05.2024" },
    ],
  },
  {
    ...STAGE_BY_ID.won,
    count: 42,
    sum: 15_600_000,
    deals: [
      { id: "0101", number: "CRM-2024-0101", company: "ООО РегионСталь", description: "Поставка металла", amount: 2_100_000, priority: "Высокий", owner: "Петров П.П.", closedDate: "12.05.2024", starred: true },
      { id: "0102", number: "CRM-2024-0102", company: "АО БетаТех", description: "Оборудование", amount: 3_750_000, priority: "Средний", owner: "Иванов И.И.", closedDate: "11.05.2024" },
      { id: "0103", number: "CRM-2024-0103", company: "ООО Стандарт", description: "Комплектующие", amount: 680_000, priority: "Низкий", owner: "Сидоров С.С.", closedDate: "10.05.2024" },
    ],
  },
];

export const FUNNEL_TOTALS: FunnelTotal[] = [
  { id: "active", label: "Сделок в работе", value: "246", delta: "+12% к прошлому периоду" },
  { id: "active-sum", label: "Сумма в работе", value: "37 200 000 ₽", delta: "+8% к прошлому периоду" },
  { id: "won", label: "Выиграно сделок", value: "42", delta: "+15% к прошлому периоду" },
  { id: "won-sum", label: "Сумма выигранных", value: "15 600 000 ₽", delta: "+10% к прошлому периоду" },
  { id: "conv", label: "Конверсия", value: "17.1%", delta: "+2.3% к прошлому периоду" },
];

export const CHATS: Chat[] = [
  { id: "1", name: "Алексей Смирнов", time: "10:24", message: "Доброе утро! Отправил КП по нашему запросу", unread: 2, kind: "person" },
  { id: "2", name: "Петров П.П.", time: "09:58", message: "Нужна спецификация по позиции 12345.", unread: 1, kind: "person" },
  { id: "3", name: "Иванов И.И.", time: "09:41", message: "Согласовали сроки поставки.", kind: "person" },
  { id: "4", name: "Сидоров С.С.", time: "09:15", message: "Подтвердите, пожалуйста, заказ на транспорт.", unread: 3, kind: "person" },
  { id: "5", name: "Отдел логистики", time: "Вчера", message: "Завтра отгрузка в Новосибирск.", kind: "logistics" },
  { id: "6", name: "Мария Волкова", time: "Вчера", message: "Можно уточнить по оплате?", kind: "person" },
  { id: "7", name: "Отдел закупок", time: "Вчера", message: "Новый поставщик на согласование.", unread: 2, kind: "purchasing" },
  { id: "8", name: "Склад", time: "Вчера", message: "Поступление на склад №4578 принято.", kind: "warehouse" },
  { id: "9", name: "Михаил Кузнецов", time: "11:05", message: "Ок, спасибо!", kind: "person" },
];

/** Подобрать детальную карточку по id сделки (для страницы /crm/deals/[id]). */
export function getDealDetail(id: string): DealDetail {
  const deal = STAGES.flatMap((s) => s.deals).find((d) => d.id === id);
  if (!deal) return DEAL_DETAIL;
  return {
    number: deal.number,
    company: deal.company,
    description: deal.description,
    amount: deal.amount,
    priority: deal.priority,
    nextStep: deal.nextStep ?? DEAL_DETAIL.nextStep,
    contact: deal.owner,
    datetime: `${deal.date ?? deal.closedDate ?? ""} • 14:00`,
    itemsTitle: DEAL_DETAIL.itemsTitle,
    items: DEAL_DETAIL.items,
    messages: DEAL_DETAIL.messages,
    focus: false,
    starred: deal.starred ?? false,
    dealDate: deal.date ?? "",
  };
}

export const DEAL_DETAIL: DealDetail = {
  number: "CRM-2024-0156",
  company: "ООО АльфаМеталл",
  description: "Поставка металлопроката",
  amount: 1_750_000,
  priority: "Высокий",
  nextStep: "Получить подписанный договор",
  contact: "Иванов П.П.",
  datetime: "12.05.2024 • 14:00",
  itemsTitle: "Маркировка металлопроката",
  items: [
    { title: "Лист горячекатаный 5 мм Ст3сп5 ГОСТ 19903-2015" },
    { title: "Арматура А500С Ø12 мм ГОСТ 34028-2016" },
  ],
  messages: [
    {
      from: "Клиент (WhatsApp)",
      channel: "whatsapp",
      time: "10:42",
      text: "Добрый день! Хотел уточнить сроки поставки листа 5 мм и возможность доставки на следующий ...",
    },
  ],
  focus: false,
  starred: true,
  dealDate: "12.05.2024",
};
