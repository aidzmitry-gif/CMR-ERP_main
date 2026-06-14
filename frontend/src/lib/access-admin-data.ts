// Demo-данные для прототипа «Управление доступом» (шаг 1 — доступ к модулям).
//
// Источник истины для матрицы/ролей/людей — backend `config/access.py`
// (ACCESS_MATRIX, ROLE_TITLES, ROLE_ORDER, USERS). Здесь — их снимок для прототипа,
// чтобы согласовать UX без записи в БД. На шаге 2 экран перейдёт на реальные
// эндпоинты (`/system/access`, будущий admin-API), а этот файл уйдёт.
//
// Метки модулей — UI-слаги сайдбара (как в access-matrix.html). Слаги
// home/analytics/it не имеют backend-модуля (фронтовые/системные).

/** Модуль системы: слаг + человекочитаемая метка (порядок = порядок столбцов). */
export interface ModuleDef {
  slug: string;
  label: string;
}

export const MODULES: ModuleDef[] = [
  { slug: "home", label: "Главная" },
  { slug: "crm", label: "CRM (продажи)" },
  { slug: "procurement", label: "Закупки" },
  { slug: "production", label: "Производство" },
  { slug: "wms", label: "Склад" },
  { slug: "logistics", label: "Логистика" },
  { slug: "finance", label: "Финансы" },
  { slug: "marketing", label: "Маркетинг" },
  { slug: "service", label: "Сервис" },
  { slug: "hr", label: "HR (кадры)" },
  { slug: "office", label: "Офис-менеджер" },
  { slug: "legal", label: "Юр. отдел" },
  { slug: "knowledge", label: "База знаний" },
  { slug: "analytics", label: "Аналитика" },
  { slug: "it", label: "IT и настройки" },
];

export const ALL_SLUGS: string[] = MODULES.map((m) => m.slug);

/** Роль = группа прав. `locked` — доступ нельзя менять (директор всегда видит всё). */
export interface RoleDef {
  slug: string;
  title: string;
  /** Полный доступ ко всему, минуя матрицу (директор/коммерческий — SUPER_ROLES). */
  superRole?: boolean;
  /** UI запрещает редактировать строку (директор). */
  locked?: boolean;
}

// Порядок и названия — ROLE_ORDER + ROLE_TITLES из config/access.py.
export const ROLES: RoleDef[] = [
  { slug: "director", title: "Директор", superRole: true, locked: true },
  { slug: "commercial", title: "Коммерческий директор", superRole: true },
  { slug: "assistant", title: "Помощник руководителя" },
  { slug: "sales_head", title: "Продажи · РОП" },
  { slug: "sales", title: "Продажи" },
  { slug: "sales_cli", title: "Продажи · работа с клиентами" },
  { slug: "procurement", title: "Закупки" },
  { slug: "warehouse", title: "Склад" },
  { slug: "logistics", title: "Логистика" },
  { slug: "production", title: "Производство" },
  { slug: "finance", title: "Финансы / офис" },
  { slug: "hr", title: "Кадры (HR)" },
  { slug: "controller", title: "Контролёр" },
];

/** Сотрудник (dev-логин). Снимок config/access.py::USERS. */
export interface Employee {
  username: string;
  full_name: string;
  role: string;
}

export const EMPLOYEES: Employee[] = [
  { username: "kharkovich_d", full_name: "Харькович Д.С.", role: "director" },
  { username: "kharkovich_s", full_name: "Харькович С.Д.", role: "commercial" },
  { username: "shlyakhtina", full_name: "Шляхтина Т.В.", role: "assistant" },
  { username: "ryazanov", full_name: "Рязанов Е.В.", role: "sales_head" },
  { username: "makarov", full_name: "Макаров", role: "sales" },
  { username: "karchevskaya", full_name: "Карчевская", role: "sales" },
  { username: "kadurin", full_name: "Кадурин", role: "sales" },
  { username: "maltsev", full_name: "Мальцев", role: "sales" },
  { username: "kravets", full_name: "Кравец", role: "sales_cli" },
  { username: "sarnatskaya", full_name: "Сарнацкая", role: "sales_cli" },
  { username: "geniseva", full_name: "Генисева А.А.", role: "procurement" },
  { username: "korneychuk", full_name: "Корнейчук Я.В.", role: "warehouse" },
  { username: "matskevich", full_name: "Мацкевич Е.М.", role: "logistics" },
  { username: "dym", full_name: "Дым", role: "production" },
  { username: "korovkin", full_name: "Коровкин", role: "production" },
  { username: "semenyuk", full_name: "Семенюк", role: "production" },
  { username: "samedov", full_name: "Самедов", role: "production" },
  { username: "rusinovich", full_name: "Русинович", role: "production" },
  { username: "zhukovskaya", full_name: "Жуковская О.Н.", role: "finance" },
  { username: "vedernikova", full_name: "Ведерникова Д.В.", role: "hr" },
];

/** Матрица «роль → доступные слаги». Снимок ACCESS_MATRIX из config/access.py. */
export const DEFAULT_MATRIX: Record<string, string[]> = {
  director: [...ALL_SLUGS],
  commercial: [...ALL_SLUGS],
  assistant: ["home", "procurement", "logistics", "office", "knowledge"],
  sales_head: ["home", "crm", "marketing", "service", "knowledge", "analytics"],
  sales: ["home", "crm", "service", "knowledge"],
  sales_cli: ["home", "crm", "service", "knowledge"],
  procurement: ["home", "procurement", "logistics", "knowledge"],
  warehouse: ["home", "wms", "logistics", "knowledge"],
  logistics: ["home", "wms", "logistics", "knowledge"],
  production: ["home", "production", "wms", "knowledge"],
  finance: ["home", "logistics", "office", "knowledge"],
  hr: [
    "home", "crm", "procurement", "production", "wms", "logistics", "finance",
    "marketing", "service", "hr", "office", "legal", "knowledge",
  ],
  // Сквозная диспетчерская/SLA-роль над задачами всех модулей (контролёр-кокпит).
  // Сейчас эти функции выполняет HR — отсюда близкий, но более узкий набор.
  controller: [
    "home", "crm", "procurement", "production", "wms", "logistics",
    "service", "office", "knowledge", "analytics",
  ],
};

/** Роль с полным доступом (администратор) — имеет любые системные функции по умолчанию. */
export function isSuperRole(role: string): boolean {
  return ROLES.find((r) => r.slug === role)?.superRole === true;
}

/**
 * Системная функция (спец-право) сверх доступа к модулям. Не «видеть раздел», а
 * «иметь право выполнить операцию» — напр. безвозвратное удаление помеченных объектов.
 */
export interface SpecialPermission {
  slug: string;
  title: string;
  description: string;
  /** Деструктивная/необратимая операция — выделяем в UI и выдаём осознанно. */
  danger?: boolean;
}

// Системные функции. Первая — администраторская операция «Удаление помеченных
// объектов»: безвозвратная зачистка объектов с пометкой на удаление после
// проверки ссылочной целостности (паттерн «пометка → удаление помеченных», как в 1С).
export const SPECIAL_PERMISSIONS: SpecialPermission[] = [
  {
    slug: "purge_marked",
    title: "Удаление помеченных объектов",
    description:
      "Безвозвратно удалять объекты, помеченные на удаление, после проверки ссылочной " +
      "целостности. Администраторская операция — выдавать точечно.",
    danger: true,
  },
];

// Какие роли (сверх администраторов) получают функцию по умолчанию: роль → слаги функций.
// Администраторы (супер-роли director/commercial и backend-роль «Админ») имеют все
// системные функции всегда, поэтому здесь их не перечисляем.
export const DEFAULT_SPECIAL_BY_ROLE: Record<string, string[]> = {};

// Поимённая выдача функции отдельным сотрудникам сверх их роли: логин → слаги функций.
export const DEFAULT_SPECIAL_BY_USER: Record<string, string[]> = {};

/** Сгруппировать сотрудников по роли (для подписи под названием роли). */
export function employeesByRole(employees: Employee[]): Record<string, Employee[]> {
  const map: Record<string, Employee[]> = {};
  for (const e of employees) (map[e.role] ??= []).push(e);
  return map;
}

// Транслитерация RU→latin для авто-генерации логина нового сотрудника.
const TRANSLIT: Record<string, string> = {
  а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
  и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
  с: "s", т: "t", у: "u", ф: "f", х: "kh", ц: "ts", ч: "ch", ш: "sh",
  щ: "shch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
};

/** ФИО → ASCII-логин (фамилия + инициал имени), как в config/access.py::USERS. */
export function makeUsername(fullName: string): string {
  const parts = fullName.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "";
  const tr = (s: string) =>
    [...s].map((ch) => (ch in TRANSLIT ? TRANSLIT[ch] : /[a-z0-9]/.test(ch) ? ch : "")).join("");
  const surname = tr(parts[0]);
  // второй токен может быть «И.О.» — берём первую букву
  const initial = parts[1] ? tr(parts[1])[0] ?? "" : "";
  return initial ? `${surname}_${initial}` : surname;
}
