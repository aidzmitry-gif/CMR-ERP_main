# Obsidian — vault CMR-ERP

## Открыть в Obsidian

1. Obsidian → **Open folder as vault**
2. Папка: `Сlaude CRM - проект/obsidian`
3. Стартовая заметка: `notes/00 Home.md`

## Структура

| Путь | Назначение |
|------|------------|
| `notes/` | Хаб-заметки и ваши записи |
| `project/` | Ссылки на корневые `.md` (PLATFORM, CLAUDE, README…) |
| `coordination/` | Junction → `../coordination` (~235 документов) |
| `docs/`, `connectors/`, `modules/`, `core/` | Junction на соответствующие папки проекта |
| `attachments/` | Вложения Obsidian |

## Что НЕ в vault

- `frontend/` (тяжёлый node_modules) — открывать в Cursor/IDE
- `data/`, `.git`, бинарники — исключены из индекса

## Исключения из индекса Obsidian

`node_modules`, `.git`, `data/`, `__pycache__`, `.next` — в `.obsidian/app.json`.
