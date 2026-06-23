// Генератор ТЗ для специалиста 1С: открыть состав OData + служебный пользователь.
// Запуск: node _docs_out/gen_tz_1c_doc.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType, LevelFormat,
} = require("docx");

const ARIAL = "Arial";
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const P = (runs, opts = {}) =>
  new Paragraph({ spacing: { after: 120 }, ...opts,
    children: Array.isArray(runs) ? runs : [new TextRun(runs)] });
const B = (t) => new TextRun({ text: t, bold: true });
const T = (t) => new TextRun(t);
const code = (t) => new TextRun({ text: t, font: "Consolas", size: 20 });
const BULLET = (runs) =>
  new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 60 },
    children: Array.isArray(runs) ? runs : [new TextRun(runs)] });
const NUM = (runs) =>
  new Paragraph({ numbering: { reference: "num", level: 0 }, spacing: { after: 80 },
    children: Array.isArray(runs) ? runs : [new TextRun(runs)] });

function cell(text, { bold = false, fill = null, w = 4680 } = {}) {
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA },
    shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text, bold })] })],
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: ARIAL, size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, font: ARIAL, color: "1F3864" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, bold: true, font: ARIAL, color: "2E5496" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 260 } } } }] },
      { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 },
      margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 } } },
    children: [
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
        children: [new TextRun({ text: "Техническое задание специалисту 1С", bold: true, size: 34, color: "1F3864" })] }),
      new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
        children: [new TextRun({ text: "Открыть доступ к данным по OData (только чтение) для внешней системы", size: 22, color: "555555" })] }),

      // --- Контекст ---
      H1("1. Что уже сделано (контекст)"),
      P([T("База — "), B("1С:Комплексная автоматизация для Беларуси, ред. 2.4"), T(" (2.4.14.182), платформа "), B("8.3.18.1661"), T(", "), B("серверный режим"), T(" (Srvr=localhost, Ref=ka_copy).")]),
      P([T("Опубликована на "), B("IIS"), T(" под именем "), code("ka_copy"), T(" (каталог "), code("C:\\inetpub\\wwwroot\\ka_copy\\"), T("). В публикации включён флажок «Публиковать стандартный интерфейс OData».")]),
      P([T("Сервис OData "), B("отвечает"), T(": по адресу "), code("http://localhost/ka_copy/odata/standard.odata/"), T(" возвращается корректный XML, ошибок нет.")]),

      // --- Проблема ---
      H1("2. Проблема, которую нужно решить"),
      P([B("Состав стандартного интерфейса OData пуст"), T(" — в ответе сервиса нет ни одной коллекции ("), code("<workspace>"), T(" без "), code("<collection>"), T("). Из-за этого внешняя система не может выгрузить ни одного объекта.")]),
      P([T("Самостоятельно открыть состав не удалось: команда «Состав стандартного интерфейса OData…» в меню Конфигуратора недоступна — предположительно потому, что "), B("конфигурация находится на поддержке"), T(" (замок у корня конфигурации) и не включена возможность изменения.")]),
      P([B("Важно: "), T("файл "), code("default.vrd"), T(" уже приведён в рабочее состояние ("), code("<standardOdata enable=\"true\" .../>"), T(" самозакрывающийся). Через "), code(".vrd"), T(" состав на платформе 8.3.18 не задаётся (платформа отвергает вложенные элементы) — состав нужно открыть штатно из Конфигуратора / режима Предприятие.")]),

      // --- Задача 1 ---
      H1("3. Задача 1 — открыть состав OData"),
      P([T("Включить в состав стандартного интерфейса OData перечисленные ниже объекты (")
        , B("только чтение"), T("). Порядок приоритета — сверху вниз; минимально обязателен п.1 (Контрагенты).")]),

      H2("Способ А — режим 1С:Предприятие (предпочтительно)"),
      NUM([T("Запустить базу "), code("ka_copy"), T(" в режиме 1С:Предприятие под пользователем с полными правами.")]),
      NUM([T("Главное меню → "), B("Все функции"), T(" → "), B("Стандартный интерфейс OData"), T(" → "), B("Настройка состава стандартного интерфейса OData"), T(". (Если «Все функции» не видно — включить в Сервис → Параметры → «Отображать команду «Все функции»».)")]),
      NUM([T("Отметить объекты из таблицы ниже → "), B("Записать"), T(".")]),

      H2("Способ Б — Конфигуратор (если нужен этот путь)"),
      NUM([T("Конфигурация → Поддержка → "), B("Настройка поддержки"), T(" → "), B("Включить возможность изменения"), T(" (снять с полной поддержки только в части, необходимой для команды; изменения объектов конфигурации НЕ требуются).")]),
      NUM([T("Меню "), B("Администрирование"), T(" → "), B("Состав стандартного интерфейса OData…"), T(" → отметить объекты → ОК.")]),

      H2("Объекты для включения в состав OData"),
      new Table({
        width: { size: 9638, type: WidthType.DXA },
        columnWidths: [620, 4200, 4818],
        rows: [
          new TableRow({ tableHeader: true, children: [
            cell("№", { bold: true, fill: "D9E2F3", w: 620 }),
            cell("Объект 1С", { bold: true, fill: "D9E2F3", w: 4200 }),
            cell("Назначение", { bold: true, fill: "D9E2F3", w: 4818 }),
          ]}),
          ...[
            ["1", "Справочник «Контрагенты»", "Клиенты — обязательный первый шаг (связка с CRM по УНП)"],
            ["2", "Справочник «Контактные лица»", "Сотрудники контрагентов"],
            ["3", "Справочник «Договоры контрагентов»", "Договоры клиентов"],
            ["4", "Справочник «Номенклатура»", "Товары/услуги (карточка: вес, код ТНВЭД, группы)"],
            ["5", "Документ «Реализация товаров и услуг» (+ табл. часть «Товары»)", "История покупок: что/когда/на какую сумму"],
            ["6", "Документ «Заказ клиента» (+ «Товары»)", "Заказы клиентов"],
            ["7", "Документ «Счёт на оплату клиенту»", "Счета"],
            ["8", "Регистр «Расчёты с клиентами» (или аналог дебиторки в КА 2.4)", "Деньги / дебиторская задолженность"],
            ["9", "Регистр сведений «Цены номенклатуры»", "История цен"],
            ["10", "Документ «Сборка (разборка) товаров», справочник «Ресурсные спецификации»", "Сборки/комплектация под клиента (если ведутся)"],
          ].map(([n, o, p]) => new TableRow({ children: [
            cell(n, { w: 620 }), cell(o, { w: 4200 }), cell(p, { w: 4818 }),
          ]})),
        ],
      }),
      P([T("Если каких-то объектов в этой конфигурации нет под такими именами — включить ближайшие аналоги и сообщить заказчику фактические имена. Минимум для старта — "), B("«Контрагенты»"), T(".")], { spacing: { before: 120, after: 120 } }),

      // --- Задача 2 ---
      H1("4. Задача 2 — служебный пользователь (только чтение)"),
      P([T("Не использовать администратора. Завести отдельного пользователя для интеграции:")]),
      BULLET([T("Имя, например, "), code("odata_user"), T(".")]),
      BULLET([B("Аутентификация 1С:Предприятия"), T(" — включить, задать пароль (нужно для HTTP Basic; доменная/ОС-аутентификация для коннектора не подходит).")]),
      BULLET([B("Роли — только чтение"), T(" на объекты из раздела 3: право «Чтение»/«Просмотр», "), B("без"), T(" «Добавление/Изменение/Удаление/Проведение». При отсутствии подходящей роли — создать роль "), code("ИнтеграцияOData_Чтение"), T(".")]),
      BULLET([T("НЕ выдавать: «Полные права», «Администрирование», запуск Конфигуратора.")]),
      BULLET([T("Учесть RLS (ограничения на уровне записей), если есть, — OData их соблюдает.")]),

      // --- Проверка ---
      H1("5. Проверка перед сдачей"),
      P([T("С машины, где есть доступ к веб-серверу 1С (подставить логин/пароль):")]),
      P([code("curl -u \"odata_user:ПАРОЛЬ\" \"http://localhost/ka_copy/odata/standard.odata/$metadata?$format=json\"")]),
      BULLET([T("Ожидаемо: список "), code("EntitySet"), T(" с включёнными объектами (напр. "), code("Catalog_Контрагенты"), T(").")]),
      P([code("curl -u \"odata_user:ПАРОЛЬ\" \"http://localhost/ka_copy/odata/standard.odata/Catalog_Контрагенты?$top=1&$format=json\"")]),
      BULLET([T("Ожидаемо: HTTP 200 и JSON с записью контрагента (поле "), code("Ref_Key"), T(").")]),
      P([T("После изменения состава может потребоваться "), code("iisreset"), T(" (PowerShell от администратора), чтобы "), code("$metadata"), T(" обновился.")], { spacing: { before: 80, after: 120 } }),

      // --- Что прислать ---
      H1("6. Что прислать заказчику по итогу"),
      P([T("Пароль — по защищённому каналу, не открытым текстом в почте/мессенджере.")]),
      NUM([B("Базовый URL OData"), T(": "), code("http://<сервер>/ka_copy/odata/standard.odata/"), T(" (или внутренний/VPN-адрес).")]),
      NUM([B("Логин и пароль"), T(" служебного пользователя 1С.")]),
      NUM([B("Список фактически открытых имён наборов сущностей"), T(" (как они называются в "), code("$metadata"), T(").")]),
      NUM([B("Версию платформы"), T(" (8.3.18.1661) — для корректного синтаксиса фильтра по дате при инкрементальной выгрузке.")]),

      // --- Безопасность ---
      H1("7. Безопасность"),
      BULLET([B("Только чтение"), T(" — у пользователя не должно быть прав на изменение.")]),
      BULLET([T("Эндпоинт OData "), B("не выставлять в открытый интернет"), T(": доступ из внутренней сети / через VPN (у заказчика настроен Tailscale, адрес сервера "), code("100.75.171.85"), T(").")]),
      BULLET([T("По возможности — "), B("https"), T(" (TLS на веб-сервере), чтобы Basic-логин/пароль не шли открытым текстом.")]),

      new Paragraph({ spacing: { before: 240 }, border: { top: { style: BorderStyle.SINGLE, size: 6, color: "2E5496", space: 6 } },
        children: [new TextRun({ text: "Никаких изменений данных со стороны внешней системы не происходит — только периодические GET-запросы небольшими страницами.", italics: true, size: 20, color: "555555" })] }),
    ],
  }],
});

const out = path.join(__dirname, "..", "ТЗ_специалисту_1С_OData.docx");
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(out, buf);
  console.log("OK:", out, buf.length, "bytes");
});
