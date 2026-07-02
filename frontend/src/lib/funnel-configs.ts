import type { FunnelKpi, FunnelPanel, FunnelSummaryMetric } from "@/lib/types";

/** Оболочечные элементы воронки под референс конкретного модуля:
 * верхние KPI «План/Факт», строка статуса, AI-инсайт, правая панель и нижние итоги.
 * Значения — демонстрационные (как в макетах-референсах); сама доска работает на живых данных. */
export interface FunnelExtras {
  createLabel: string;
  kpis: FunnelKpi[];
  statusNote: string;
  insight?: string;
  panel: FunnelPanel;
  summary: FunnelSummaryMetric[];
  conversion?: boolean;
  leaderboard?: { name: string; meta: string; value: string }[];
}

export const FUNNEL_EXTRAS: Record<string, FunnelExtras> = {
  procurement: {
    createLabel: "Создать закупку",
    kpis: [
      { label: "Заявки в работе", value: "32", target: "40", note: "80% от плана", percent: 80, tone: "blue" },
      { label: "План по сумме закупок", value: "24,8 млн", target: "30 млн ₽", note: "83% выполнено", percent: 83, tone: "green" },
      { label: "Экономия (AI)", value: "1,85 млн", target: "2 млн ₽", note: "93% от цели месяца", percent: 93, tone: "violet" },
      { label: "Переговоры AI", value: "24", target: "30", note: "80% слотов загружено", percent: 80, tone: "amber" },
      { label: "Приёмка / QC сегодня", value: "6", target: "10", note: "60% инспекций", percent: 60, tone: "cyan" },
    ],
    statusNote: "AI ведёт 18 закупок автономно · 3 просрочки · 2 ждут approval · 01.05 – 31.05.2025",
    insight:
      "цены на AGM-аккумуляторы на 1688 упали на 6%. Рекомендую перенести 3 закупки на эту неделю — прогноз экономии ≈ 210 000 ₽. Риски поставки: низкие.",
    panel: {
      title: "AI-агенты и поставщики",
      tabs: ["Лента", "Поставщики", "Задачи"],
      items: [
        { title: "Procurement Orchestrator", text: "План закупок на неделю готов, прогноз экономии 210 000 ₽", tone: "ai", badge: 3 },
        { title: "Negotiation Agent", text: "Shenzhen SunPower: −8% от прайса согласовано", tone: "ai" },
        { title: "Supplier Agent", text: "Найдено 12 поставщиков AGM 12V 200Ah (1688/Alibaba)", tone: "ai" },
        { title: "Risk Agent", text: "Возможна задержка по заявке 0335 — около 5 дней", tone: "alert", badge: 1 },
        { title: "Price Monitor", text: "MPPT-контроллеры: цены снизились на 4%", tone: "info" },
        { title: "QC Agent", text: "Инспекция партии 0345 пройдена, брак 0%", tone: "ok" },
      ],
    },
    summary: [
      { label: "Закупок в работе", value: "142", delta: "+9%" },
      { label: "Сумма закупок", value: "24,8 млн ₽", delta: "+12%" },
      { label: "Сэкономлено (AI)", value: "1,85 млн ₽", delta: "+18%" },
      { label: "Завершено", value: "38", delta: "+6%" },
      { label: "Supplier Score", value: "8,6 / 10", delta: "+0.3" },
      { label: "Поставки в срок", value: "91,4%", delta: "+2.3%" },
    ],
  },

  production: {
    createLabel: "Создать наряд",
    kpis: [
      { label: "План на день", value: "186", target: "320 шт", note: "58% плана · темп в графике", percent: 58, tone: "blue" },
      { label: "Загрузка линий (OEE)", value: "82%", note: "5 линий активны · 1 на ТО", percent: 82, tone: "green" },
      { label: "Обеспеченность", value: "86%", note: "2 наряда с дефицитом", percent: 86, tone: "amber" },
      { label: "Контроль ОТК сегодня", value: "12", target: "18", note: "брак 1.8% · норма ≤ 2%", percent: 67, tone: "cyan" },
      { label: "Нарядов в производстве", value: "24", target: "30", note: "WIP 2 980 шт", percent: 80, tone: "indigo" },
    ],
    statusNote: "AI ведёт 6 нарядов · 3 наряда — риск срыва · 2 линии перегружены · смена №1 · 04.06.2026",
    insight:
      "на участке сборки прогноз простоя ≈ 1 день — дефицит BMS по наряду 0184 (нужно 36 шт). Решение: переставить наряд 0190 вперёд и взять 36 BMS из резерва — план смены выполнится на 100%.",
    panel: {
      title: "Цех · сегодня",
      items: [
        { title: "Дефицит BMS — наряд 0184", text: "Нужно 36 шт · риск простоя 1 день", tone: "alert", badge: 1 },
        { title: "ОТК: 2 ед. на переборку", text: "Наряд 0176 · отклонение напряжения", tone: "alert" },
        { title: "AI: переставить наряд 0190", text: "Взять 36 BMS из резерва — план смены 100%", tone: "ai" },
        { title: "AI: наряд 0179 → линия 3", text: "Загрузка 46% — ускорение на 1 день", tone: "ai" },
        { title: "Линия 2 — плановое ТО", text: "Через 2 ч · окно 30 мин", tone: "info" },
        { title: "Сверхурочные · сборка", text: "+2 ч · бригада №2 — ждёт согласования", tone: "info" },
      ],
    },
    summary: [
      { label: "Нарядов в работе", value: "24", delta: "+8%" },
      { label: "План месяца, шт", value: "6 800", delta: "62% готово" },
      { label: "Выпущено, шт", value: "4 240", delta: "+11%" },
      { label: "OEE", value: "82%", delta: "+3.4%" },
      { label: "Брак", value: "1,8%", delta: "−0.6%" },
      { label: "Сдано в срок", value: "93,5%", delta: "+2.1%" },
    ],
  },

  wms: {
    createLabel: "Создать поступление",
    kpis: [
      { label: "Приёмки сегодня", value: "8", target: "12", note: "67% выполнено", percent: 67, tone: "blue" },
      { label: "Сумма к отгрузке", value: "6,2 млн", target: "9 млн ₽", note: "69% выполнено", percent: 69, tone: "green" },
      { label: "Заказов к сборке", value: "18", target: "25", note: "72% выполнено", percent: 72, tone: "violet" },
      { label: "Контроль качества", value: "6", target: "10", note: "60% выполнено", percent: 60, tone: "amber" },
      { label: "Инвентаризация · зона B", value: "320", target: "500 поз.", note: "64% пересчитано", percent: 64, tone: "cyan" },
    ],
    statusNote: "Цикл: поступление → приёмка → контроль → размещение → отгрузка · 01.05 – 31.05.2024",
    panel: {
      title: "Чаты и дела",
      chat: true,
      items: [
        { title: "Отдел закупок", text: "Поставка по CRM-0156 завтра к 14:00, готовьте зону A", tone: "info", badge: 2 },
        { title: "Производство", text: "Партия №П-441 готова к приёмке на склад", tone: "info", badge: 1 },
        { title: "ОТК · Качество", text: "По приёмке ПР-0132 выявлен брак 2 поз., нужен акт", tone: "alert" },
        { title: "Отдел логистики", text: "Машина прибудет в 14:00, разгрузка — зона A", tone: "info", badge: 3 },
        { title: "Сидоров С.С.", text: "Зона B размещена, начинаю инвентаризацию", tone: "ok" },
        { title: "Финансы", text: "Акт расхождений по ПР-0132 на −180 000 ₽ принят", tone: "info" },
      ],
    },
    summary: [
      { label: "Позиций принято", value: "1 248", delta: "+12%" },
      { label: "Отклонения", value: "−18 поз.", delta: "−420 000 ₽" },
      { label: "Позиций собрано", value: "892", delta: "+8%" },
      { label: "Отгружено позиций", value: "845", delta: "+15%" },
      { label: "Сумма отгрузок", value: "15,6 млн ₽", delta: "+10%" },
      { label: "Точность инвент.", value: "98,6%", delta: "+0.4%" },
    ],
  },

  hr: {
    createLabel: "Создать вакансию",
    kpis: [
      { label: "Открытых вакансий", value: "14", target: "18", note: "78% закрыто в срок", percent: 78, tone: "blue" },
      { label: "Интервью сегодня", value: "9", target: "12", note: "75% проведено", percent: 75, tone: "green" },
      { label: "Офферов в работе", value: "5", target: "6", note: "83% принято", percent: 83, tone: "amber" },
      { label: "Новых откликов", value: "38", target: "50", note: "76% обработано", percent: 76, tone: "violet" },
      { label: "Выходов на неделе", value: "4", target: "5", note: "80% по графику", percent: 80, tone: "cyan" },
    ],
    statusNote: "Воронка подбора — от создания вакансии до прохождения испытательного срока",
    panel: {
      title: "Чаты и контакты",
      chat: true,
      items: [
        { title: "Соколова А. (рекрутер)", text: "Смирнова А. подтвердила скрининг на 15:00", tone: "info", badge: 2 },
        { title: "Ковалёв Сергей", text: "Готов прийти на интервью в четверг", tone: "ok" },
        { title: "Морозов Д. (рекрутер)", text: "Согласовать вилку по бухгалтеру с финдиректором", tone: "info" },
        { title: "hh.ru", text: "6 новых откликов на «Менеджер по продажам»", tone: "info", badge: 6 },
        { title: "Никитина Ольга", text: "Прислала тестовое задание", tone: "ok" },
      ],
    },
    summary: [
      { label: "Закрыто вакансий", value: "9", delta: "+2" },
      { label: "Ср. время на вакансию", value: "24 дн", delta: "−3 дн" },
      { label: "Интервью проведено", value: "42", delta: "+12%" },
      { label: "Успешных наёмов", value: "7", delta: "+1" },
      { label: "Средняя зарплата", value: "118 000 ₽", delta: "+4%" },
      { label: "Принятых офферов", value: "83%", delta: "+5%" },
    ],
    conversion: true,
    leaderboard: [
      { name: "Соколова А.", meta: "Отдел подбора · 5 закрыто", value: "92%" },
      { name: "Морозов Д.", meta: "Отдел подбора · 4 закрыто", value: "84%" },
      { name: "Иванова Е.", meta: "Отдел подбора · 3 закрыто", value: "78%" },
    ],
  },

  office: {
    createLabel: "Новая сделка",
    kpis: [
      { label: "Отгрузки сегодня", value: "12", target: "18", note: "67% выполнено", percent: 67, tone: "blue" },
      { label: "Документы к проверке", value: "9", target: "14", note: "64% обработано", percent: 64, tone: "violet" },
      { label: "Ожидают оплаты", value: "19", target: "24", note: "79% закрыто", percent: 79, tone: "cyan" },
      { label: "Сумма к получению", value: "5,6 млн", target: "7,2 млн ₽", note: "78% собрано", percent: 78, tone: "green" },
      { label: "Просрочка → юр. отдел", value: "3", target: "5", note: "2 на контроле", percent: 60, tone: "red" },
    ],
    statusNote: "Документооборот после продажи · 01.05 – 31.05.2024",
    panel: {
      title: "Чаты",
      chat: true,
      items: [
        { title: "ООО МеталлПром", text: "Когда планируете отгрузку по 0156?", tone: "info", badge: 1 },
        { title: "Склад", text: "Заказ 0156 собран, готов к отгрузке", tone: "ok" },
        { title: "ПАО ХимПром", text: "Пришлём недостающие УПД и ТТН завтра", tone: "info" },
        { title: "Бухгалтерия", text: "Оплата по 0101 поступила", tone: "ok" },
        { title: "Дмитрий М.", text: "Передал документы по 0122 в контроль оплаты", tone: "info" },
      ],
    },
    summary: [
      { label: "Дел в работе", value: "79", delta: "+7%" },
      { label: "Сумма к получению", value: "5,6 млн ₽", delta: "+9%" },
      { label: "Дел завершено", value: "64", delta: "+11%" },
      { label: "Сумма собрана", value: "21,3 млн ₽", delta: "+8%" },
      { label: "Средний цикл", value: "6 дн", delta: "−1 дн" },
    ],
  },

  legal: {
    createLabel: "Создать дело",
    kpis: [
      { label: "Договоры на согласовании", value: "8", target: "12", note: "67% выполнено", percent: 67, tone: "blue" },
      { label: "Претензии к отправке", value: "5", target: "8", note: "63% выполнено", percent: 63, tone: "amber" },
      { label: "Сумма к взысканию", value: "4,5 млн", target: "8 млн ₽", note: "56% выполнено", percent: 56, tone: "green" },
      { label: "Судебные заседания", value: "3", target: "4", note: "75% выполнено", percent: 75, tone: "indigo" },
      { label: "Контроль сроков", value: "14", target: "20", note: "3 истекают сегодня", percent: 70, tone: "red" },
    ],
    statusNote: "Контроль документов и взыскание · 01.05 – 31.05.2024",
    panel: {
      title: "Чаты и дела",
      chat: true,
      items: [
        { title: "Бухгалтерия", text: "Подтвердите сумму долга по ООО АльфаМеталл", tone: "info", badge: 1 },
        { title: "ФССП", text: "Исполнительное производство по ИП Сидоров возбуждено", tone: "info" },
        { title: "Нотариус", text: "Исполнительная надпись готова к выдаче", tone: "ok" },
        { title: "Арбитражный суд", text: "Заседание по делу 0009 назначено на 15.06", tone: "alert", badge: 1 },
        { title: "Фин. директор", text: "Согласовал претензию на 1,75 млн", tone: "ok" },
      ],
    },
    summary: [
      { label: "Дел в работе", value: "98", delta: "+11%" },
      { label: "Сумма к взысканию", value: "14,2 млн ₽", delta: "+6%" },
      { label: "Дел завершено", value: "64", delta: "+9%" },
      { label: "Сумма взыскана", value: "18,3 млн ₽", delta: "+14%" },
      { label: "Эффективность", value: "87%", delta: "+3%" },
    ],
  },

  knowledge: {
    createLabel: "Создать курс",
    kpis: [
      { label: "Курсы пройдено", value: "12", target: "28", note: "43% программы", percent: 43, tone: "blue" },
      { label: "Обязательные курсы", value: "8", target: "10", note: "2 курса просрочены", percent: 80, tone: "red" },
      { label: "В процессе", value: "5", target: "16", note: "31% активных", percent: 31, tone: "cyan" },
      { label: "Часов изучено", value: "36", target: "60 ч", note: "60% плана", percent: 60, tone: "green" },
      { label: "Сертификаты", value: "3", target: "8", note: "3 получено", percent: 38, tone: "violet" },
    ],
    statusNote: "Программа обучения · от тестовой недели до развития сотрудников",
    panel: {
      title: "Мои дедлайны",
      items: [
        { title: "Охрана труда (ТБ)", text: "Обязательный курс не пройден — сегодня", tone: "alert", badge: 1 },
        { title: "Корпоративная этика", text: "Тест нужно сдать — 2 дня", tone: "alert" },
        { title: "Промпт-инжиниринг", text: "Завершить практику — Пт", tone: "info" },
        { title: "Цели на испыт. срок", text: "Согласовать с наставником — 16.05", tone: "info" },
        { title: "Достижение: ИИ-старт", text: "Первый ИИ-курс пройден", tone: "ok" },
        { title: "Рейтинг отдела", text: "Вы на 2-м месте — 84%", tone: "ok" },
      ],
    },
    summary: [
      { label: "Сотрудников в обучении", value: "38", delta: "+5" },
      { label: "Курсов завершено", value: "142", delta: "+18%" },
      { label: "Средний балл тестов", value: "87%", delta: "+3%" },
      { label: "Сертификатов выдано", value: "24", delta: "+12%" },
      { label: "Завершаемость", value: "76%", delta: "+4%" },
    ],
  },

  service: {
    createLabel: "Создать заявку",
    kpis: [
      { label: "Заявок в работе", value: "12", target: "20", note: "60% от плана", percent: 60, tone: "blue" },
      { label: "Закрыто сегодня", value: "4", target: "8", note: "50% плана", percent: 50, tone: "green" },
      { label: "SLA выполнен", value: "87%", note: "цель ≥ 90%", percent: 87, tone: "amber" },
    ],
    statusNote: "12 заявок в работе · 3 просрочены · 2 ждут ответа",
    panel: {
      title: "Активные обращения",
      tabs: ["Лента", "Клиенты", "Задачи"],
      items: [
        { title: "Онбординг: сделка CRM-042", text: "Клиент подключён, ждёт инструкций", tone: "info" },
        { title: "Рекламация #SR-007", text: "Ожидает ответа клиента 2 дня", tone: "alert", badge: 1 },
        { title: "Техподдержка #SR-011", text: "Решено, ожидает закрытия", tone: "ok" },
      ],
    },
    summary: [
      { label: "Всего заявок", value: "38", delta: "+5%" },
      { label: "Закрыто", value: "26", delta: "+8%" },
      { label: "SLA", value: "87%", delta: "-2%" },
      { label: "Среднее время", value: "4.2 ч", delta: "-0.3" },
    ],
  },
};
