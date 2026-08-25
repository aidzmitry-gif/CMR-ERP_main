---
tags:
  - erp
  - moc
---

# CMR-ERP — AI-First Business OS

Главная карта знаний. Документация проекта — через папки-ссылки (`coordination/`, `docs/`, `modules/` …).

## Быстрый старт

| Тема | Заметка |
|------|---------|
| Конституция платформы | [[project/PLATFORM]] |
| Контекст для Claude | [[project/CLAUDE]] |
| Сервер / деплой | [[docs/SERVER]] |
| README проекта | [[project/README]] |
| Архитектура | [[project/Архитектура_и_план_AI-First_OS]] |

## Выгрузка данных (1С + Bitrix24)

- [[coordination/plan-safe-export-1c-bitrix|План безопасной выгрузки]] — фазы 0→T→1–7
- [[connectors/README|Коннекторы сбора]]
- [[connectors/connectors_spec|ТЗ коннекторов]]
- [[coordination/spec-backfill-nov2024|Карта приземления данных в ERP]]

## Стратегия и архитектура

- [[coordination/erp-replace-bitrix-1c-strategy|Стратегия: Bitrix + 1С → наша ERP]]
- [[coordination/DEPENDENCY-MAP|Карта зависимостей модулей]]
- [[coordination/mdm-data-class-seam|MDM: контрагенты, блокеры импорта]]

## Модули (по полосам)

- [[modules/sales/CLAUDE|Продажи (sales)]]
- [[modules/procurement/CLAUDE|Закупки (procurement)]]
- [[modules/finance/CLAUDE|Финансы (finance)]]
- [[modules/wms/CLAUDE|Склад (WMS)]]
- [[core/reference/CLAUDE|Справочники / MDM]]

## Аналитика и планирование

- [[coordination/pricing-methodology|Методика цены (landed cost)]]
- [[sales-regular-clients|Постоянные клиенты — каденция контактов]]
- [[plan-export-summary|Сводка: маржа, min/max, кому звонить]]

## Координация (живые документы)

- [[coordination/STATUS|STATUS]]
- [[coordination/ACTIVE-SESSIONS|Активные сессии]]
- [[coordination/REPORTS|Отчёты]]

## Внешние ссылки

- GitHub: [CMR-ERP_main](https://github.com/aidzmitry-gif/CMR-ERP_main.git)
- Сервер: `tailscale ssh root@100.70.224.109` → `/opt/cmr-erp`
