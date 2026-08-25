# docs-trash — задание воркеру

Файлы-макеты (корень репо, self-contained HTML, inline JS, офлайн): **`sales-card-full.html`** (карточка сделки) и **`sales-docs-purge.html`** (модуль «Архив документов», вне CRM, безвозвратное удаление). Бэкенда нет.

## Цель (Goal-Driven)
Сейчас в `sales-docs-purge.html` список `ITEMS` — статичный демо-массив. Нужно связать его с **реальными пометками на удаление**, которые менеджер ставит в карточке сделки. Слой обмена — **`localStorage`** (оба файла открываются в одном браузере).

Проверка-цель: «в карточке сделки пометил документ на удаление (🗑) → запись появилась в localStorage → открыл sales-docs-purge.html → документ виден в списке; "Восстановить" и "Удалить безвозвратно" обновляют localStorage (и при возврате в карточку пометка снята при восстановлении)».

## Что уже есть (изучи перед правкой)
В `sales-card-full.html`:
- `markDoc(i)` / `unmarkDoc(i)` — ставят/снимают `d.docs[i].del` (документ).
- `markVer(i,vi)` / `unmarkVer(i,vi)` — ставят/снимают `history[vi].del` (версия).
- `DEALS[currentKey]` — текущая сделка; у сделки есть `num` (напр. «№ CRM-1029»), `company`, `docs[]` (n, kind, ver, history…).
- `render(currentKey)`, `toast(msg)` — есть.

В `sales-docs-purge.html`:
- `ITEMS` (демо-массив), `render()`, `restore(id)`, `purge(id)`, `toast()`.

## Что сделать
1. В `sales-card-full.html`: при пометке (markDoc/markVer) — **записать** в localStorage ключ `'docTrash'` (массив JSON) запись: `{id, n (имя), kind, deal (номер+клиент), ver, by, at, reason}`; при снятии (unmarkDoc/unmarkVer) — **удалить** соответствующую запись из этого массива. `id` — стабильный (напр. `${currentKey}|${имя}|${ver}`). Существующее поведение (d.docs[i].del, render, toast) сохранить.
2. В `sales-docs-purge.html`: при загрузке **читать** `localStorage['docTrash']` и формировать `ITEMS` из него; если пусто/нет ключа — оставить нынешний демо-массив как **fallback** (чтобы экран не был пустым на чистом профиле). `restore(id)` и `purge(id)` должны **писать обратно** в localStorage (restore удаляет запись; purge удаляет запись). Не падать, если localStorage недоступен (file:// обычно ок, но обернуть в try/catch).

## Проверка (обязательно)
- `node ".claude/skills/ui-crawl/scripts/handler-audit.mjs" sales-card-full.html sales-docs-purge.html` → оба `MISSING: none ✓`, `JS OK ✓`.
- Если есть браузер — :8899, пометить в карточке → открыть архив → увидеть; иначе обосновать логикой + STR.

## Границы
- Трогать **только** `sales-card-full.html` и `sales-docs-purge.html`.
- Не пушить. Коммит локальный, six-layer тело. localStorage обернуть в try/catch.
