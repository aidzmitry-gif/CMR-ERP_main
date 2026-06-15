# Справочники-фронт — ОБЩИЙ контракт для всех воркеров (sp-1…sp-7)

Один блок правил для всех 7 экранов вкладки «Справочники». Полное ТЗ и таблица экранов —
`coordination/reference-fe-scope.md` (читать обязательно). Здесь — то, что одинаково у всех,
чтобы 7 экранов вышли в одном стиле и не дрались за файлы.

## Канонический паттерн страницы (КОПИРУЙ структуру)

Эталон LIVE-экрана со SSR + ролью — `frontend/src/app/erp/production/norms/page.tsx`:

```tsx
// app/erp/spravochniki/<путь>/page.tsx — ТОНКАЯ серверная страница (async)
import { AppShell } from "@/components/app-shell";
import { МойЭкран } from "@/components/erp/spravochniki/<имя>";
import { currentRole } from "@/lib/role-server";
// import { fetch... } from "@/lib/reference-data";  // SSR-чтение

export default async function Page() {
  const role = await currentRole();
  const data = await fetch...Server(role);       // через готовый клиент reference-data.ts
  return (
    <AppShell crumbs={["ERP", "Справочники", "<Название экрана>"]}>
      <МойЭкран initial={data} />
    </AppShell>
  );
}
```

Клиентский компонент — `frontend/src/components/erp/spravochniki/<имя>.tsx`, начинается с
`"use client"`, получает SSR-данные пропсом `initial`, интерактив/мутации — через готовые
функции `reference-data.ts` (клиентские мутации бьют в `/api/*`, см. сам клиент).
Образец стиля клиентского компонента — `frontend/src/components/erp/access-admin.tsx`.

## API — ТОЛЬКО через готовый клиент (НЕ трогать его)

`frontend/src/lib/reference-data.ts` — **read-only, заморожен**. Все функции уже есть
(см. §«Что уже есть» в reference-fe-scope.md). НЕ добавляй сюда ничего. Если нужна новая
**чистая** логика (группировка/фильтр/формат) — заводи ОТДЕЛЬНЫЙ файл
`frontend/src/lib/spravochniki-<screen>.ts` + co-located `*.test.ts` (vitest). Так воркеры
не пересекаются.

## Развязка файлов (НЕ лезь в чужое)

- Свой маршрут: `app/erp/spravochniki/<свой-путь>/**` — только он.
- Свой компонент: `components/erp/spravochniki/<уникальное-имя>.tsx` — имя из своего scope.
- Своя чистая логика (если нужна): `lib/spravochniki-<screen>.ts` (+ тест).
- **Навигация между экранами** — НЕ общий компонент (чтобы не драться). Каждый экран рисует
  свою шапку-ссылки сам (маленький локальный массив ссылок на 7 маршрутов — дублирование ок).
  Хаб-страница `/erp/spravochniki` (экран sp-1) даёт карточки-ссылки на все экраны.
- **ЗАПРЕЩЕНО** трогать: `frontend/src/lib/reference-data.ts`, `frontend/src/lib/api.ts`,
  `frontend/src/components/sidebar.tsx`, `core/**`, `modules/**`, миграции. Пункт меню в
  сайдбаре — НЕ твоя задача (отдельная интеграция оркестратором).

## Дизайн (как в макете spravochniki-*-preview.html)

- Токены ровно как в проекте: `canvas/ink/muted/brand` + `shadow-card`, `rounded-2xl`. Деньги — **BYN**.
- Иконки — `lucide-react` (уже в проекте). Никаких новых глобальных стилей и зависимостей.
- Внешний вид экрана должен соответствовать своему `spravochniki-<…>-preview.html` (сетка/иконки/бейджи).

## LIVE vs ДЕМО (честность)

- LIVE-секции рендерят реальные данные из клиента; при недоступном бэке — graceful degrade
  (клиент уже отдаёт `[]`/`null`, покажи пустое состояние, не падай).
- ДЕМО-секции (где гэп бэкенда) — **визуально помечать** плашкой/бейджем «демо», НЕ выдавать за live.
- Пустое ≠ демо: напр. аудит в карточке контрагента сейчас реально пуст (нет событий) — это
  «истории пока нет», а не демо.

## Приёмка (гейт — у каждого экрана)

- `npx tsc --noEmit` в `frontend/` — **чисто** (lint в проекте не настроен, tsc — гейт).
- Новая чистая логика покрыта co-located vitest; `npx vitest run <свой файл>` — зелено.
- Внешний вид соответствует своему `spravochniki-*-preview.html`.
- Коммит мелко (1 экран = 1+ коммитов), six-layer в теле. **Без push.**
- Тронуты ТОЛЬКО файлы своего scope (свой маршрут + свой компонент + опц. своя lib + тест).

## Гоча окружения

- Локальный backend для проверки SSR: `BACKEND_URL=http://127.0.0.1:8000` (НЕ `localhost` —
  Node резолвит в IPv6 `::1`, uvicorn слушает IPv4 → SSR молча уходит в fallback).
- Если бэкенд не поднят — это нормально: проверяй `tsc`/`vitest`, а LIVE-данные — по graceful degrade.
