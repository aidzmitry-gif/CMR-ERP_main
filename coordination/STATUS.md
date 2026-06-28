# Готовность проекта (snapshot)

> **Обновлено:** 2026-06-12
> **Как обновить метрики:** `python scripts/readiness.py` → перенести объективные цифры сюда.
> **% — субъективная оценка** (учитывает зрелость UI, AI-мок, наличие миграций); правится вручную при реальном сдвиге блока, не каждую сессию.
> Этот файл **не грузится автоматически** в контекст — читать по запросу «сколько готово».

## Средняя готовность платформы: **~42–45%**

| Модуль | loc / роуты | Миграции | Фронт | % |
|---|---|---|---|---|
| **CRM / Продажи** (эталон) | 2439 / 41 | 12 | bespoke: DealsWorkspace, LeadsWorkspace, РОП, Owner | **70** |
| **Логистика** | 2793 / 45 | 5 | живой 6-вкладочный воркспейс (тендер/тарифы/автопарк/доставка/insights/scorecard/аудит) | **65** |
| **Производство** | 1223 / 30 | 4 | FunnelBoard + панели (BOM/ОТК/нормы/выработка) | **55** |
| **Закупки** | 1830 / 28 | 4 | FunnelBoard + 5 экранов (заказы/редактор/поставщики/RFQ/претензии) + MRP-lite | **68** |
| **Склад (WMS)** | 317 / 6 | 0 (на shared stock) | FunnelBoard | **38** |
| **HR** | 225 / 6 | 0 | FunnelBoard | **33** |
| **Юр / База знаний / Офис** | ядро-заглушки | 0 | FunnelBoard (demo) | **30** |
| **Финансы** | 150 / 3 | 0 | ModuleBoard | **25** |
| **Маркетинг** | 121 / 3 | 0 | ModuleBoard | **25** |
| **Сервис** | 92 / 2 | 0 | ModuleBoard | **20** |
| Ядро-платформа | contract/loader/eventbus/outbox/RBAC | — | — | **75** |

Всего миграций: **36**.

> Примечание: у sales/logistics `page.tsx` тонкий (10–14 loc), потому что делегирует
> в богатый компонент-воркспейс — это самый зрелый UI, а не отсутствие фронта.

## Сквозные факторы (тянут вниз ВСЕХ)
- **AI-слой — «Итерация-1»**: моки/ghost-плейсхолдеры по дизайну, реальных агентов нет.
- **Прод-БД не наполнена** (нет seed) → живые доски/таблицы на belakb.by пустые.
- **KPI-числа — статичные demo** (`FUNNEL_EXTRAS`), а не из БД.
- **Безопасность — зрелость ~2/5** (P0 почти закрыт, 2026-06-24): fail-closed (роль «Гость»),
  мутации `/system/*` под `system.write`, `.dockerignore`, прод-дефолты `debug=False`/прод-гард,
  Telegram-webhook secret-token (fail-closed в проде), БД/Redis published-порты на loopback.
  456 тестов зелёные. Осталось в P0: SOPS + ротация секретов, P0-0 (проверить экспозицию прода),
  bind app/keycloak на loopback (зависит от топологии прокси — ops). Полноценная AuthN/AuthZ
  (Keycloak/RBAC) — P1. План и модель угроз — `SECURITY.md`. Цель: P0+P1 → твёрдая 3/5.

## Тип UI — что значит
- **bespoke** — кастомный воркспейс (живые данные + богатый UI). Самый зрелый.
- **FunnelBoard** — канбан+KPI; доска живая, KPI-числа demo.
- **ModuleBoard** — простая generic-таблица (CRUD-каркас).

<!-- READINESS:AUTO — авто-блок scripts/readiness.py --write, не редактируй вручную -->
### Объективные метрики (авто, обновлено 2026-06-28)

Свежие цифры из кода: loc (без миграций) · роуты · миграции модуля · тип фронта.
Таблица с **%** выше — курируемая вручную; сверяй её с этими числами.

| пакет | loc | роуты | мигр | ui |
|---|---:|---:|---:|---|
| `sales` | 5237 | 69 | 18 | bespoke (33 loc) |
| `procurement` | 1830 | 28 | 4 | FunnelBoard |
| `production` | 1223 | 30 | 4 | FunnelBoard |
| `wms` | 2479 | 42 | 6 | bespoke (15 loc) |
| `logistics` | 3306 | 51 | 5 | bespoke (10 loc) |
| `finance` | 1378 | 13 | 3 | bespoke (10 loc) |
| `marketing` | 121 | 3 | 0 | ModuleBoard |
| `service` | 92 | 2 | 0 | ModuleBoard |
| `hr` | 225 | 6 | 1 | FunnelBoard |
| **всего миграций** | | | **71** | |

<!-- /READINESS:AUTO -->

<!-- COORD:AUTO — снимок координации флота, scripts/readiness.py --write -->
### Координация флота (авто, 2026-06-28 10:28)

- Ветка `sales-2.0-redesign` · HEAD `4d6f718 feat(refs): REF3-9 — read-only dry-run проба моста кэш 1С → MDM` · впереди origin **119** · незакоммичено **545**
- Голова миграций (alembic): **0071**

**Открытые доклады полос (REPORTS.md):**
- - `2026-06-28 00:24` · сессия `2270ceed` · **КООРД:** DONE Закупки — ТЗ закрыто: landed cost facade + PurchaseOrder/ETA + /cost-estimate (Китай) + эмит landed_cost.calculated (qty+total для finance); миграция 0056; 20 backend + 7 fe тестов; [DoD ✓review ✓tests ✓lint ✓commit ✓one-head] ⚠ общий worktree склеил мой 185cdda с logistics-стейджем (modules/logistics+test_logistics_tender) — нужны per-session worktree; §2/счётчик за координатором`
- - `2026-06-28 01:00` · сессия `ce567d7c` · **КООРД:** DONE Финансы — операц. финконтур P1-P11 закрыт; миграции 0061+0063 (down=0060/0062); 8 локальных коммитов: super 2fccdbf/f469ece/91a1597 + fin-7 20411ce/de2ba38; 23 pytest pass [DoD: ✓review(self) ✓tests(23 PASS finance) ✓lint(ruff+tsc finance) ✓commit(локально, не пушено) ✓migration(0061+0063 in linear chain, head=0066) ✗depmap(§2 — за координатором)] · qty в landed payload получен (закупки 178d3be) — landed-маржа зажглась через total_landed_byn
- - `2026-06-28 01:01` · сессия `ce567d7c` · **КООРД:** DONE Финансы — ТЗ `_tz_finance.md` P1-P11 закрыт ранее в этом заходе (связь падала уже после финального доклада); состояние подтверждено: 23 pytest PASS, миграции 0061+0063 в линейном чейне (head 0066), 8 локальных коммитов fin-7+super, ничего недоделанного не осталось — жду команды на push или следующий ТЗ
- - `2026-06-28 01:27` · сессия `c3a71f5f` · **КООРД:** DONE Логистика — все 10 пунктов ТЗ закрыты (D1 негоциация/торг • D2 info-подписка procurement.received → новое событие logistics.import.received • D3 ShipmentDrawer+таймлайн • D4 ручной трекинг+DELIVERY_FLOW transitions • D5 CRUD перевозчиков+тарифов • D6 bid_risk (медиана+флаг демпинга) + зеркало bidRisk на фронте • D7 форма приёмки счёта • D8 ImportDrawer+ИНФО-продвижение • D9 правка KPI+recompute • D10 явные error-состояния); миграция 0061 НЕ потребовалась (схему не трогал, только PATCH-эндпоинты); **новое событие шины `logistics.import.received` (INFO)** — пометить в DEPENDENCY-MAP §2 за координатором; ⚠ side-info: sales' коммит `f68a55d` ломает full-app load (`NameError: DealHandoffOut` в `modules/sales/routes.py:891`) — все api-fixture тесты падают, чужая зона, фикс за полосой Продажи; DoD: ✓review(self+ruff+tsc) ✓tests(pytest unit 12 PASS + vitest 29 PASS; api-fixture тесты блокирует sales-NameError) ✓lint(ruff+tsc чисто) ✓commit(локально, инкрементально, по именам; не пушено).
- - `2026-06-28 01:30` · сессия `1b5d8576` · **КООРД:** DONE Продажи — ТЗ_tz_sales.md 11/11 закрыт: факт-маржа через landed cost (П1+П2), мульти-воронки + миграция 0062 + переключатель (П3+П4+П5), pipeline-аналитика API+UI (П6+П7), встречный план РОП на PlanTarget (П8+П9), won→office handoff контракт (П10), 21 PASS sales-suite (П11) [DoD: ✓review(ручной+ruff+tsc) ✓tests(21 PASS) ✓lint ✓commit(локально, не пушено, по именам) ✓migration(0062 один head — впишите в §5) ✗depmap(новое событие sales.deal.handoff — за координатором §2)]; NEEDS-MIG 0062 (Deal.funnel/Stage.funnel) и INFO sales.deal.handoff в граф межмодульных связей.`
- - `2026-06-28 01:42` · сессия `bfb82d3b` · **КООРД:** DONE Склад — складское ядро по `_tz_wms.md` (приёмка+QC, put-away/pick, волна+pack, сверка с 1С, low-stock, цикл-каунт, дашборд, этикетки, навигация); миграции 0064/0066/0068/0069 (head один=0070, линейна); адверсариальное ревью → 3 фикса (крит. RBAC воронки, деньго-кламп дефицита, populate); всё локально, НЕ пушено [DoD: ✓review(multi-agent+фиксы) ✓tests(pytest -k wms 15 passed; vitest зелёные) ✓lint(ruff . + tsc) ✓one-head(0070) ✓commit(инкрементально локально) ✗push(правило владельца) ✗depmap(§2 ребро sales.stock.released→wms — за координатором)]
- - `2026-06-28 01:48` · сессия `2270ceed` · **КООРД:** DONE Закупки — ТЗ 11/11 (поставщики+scorecard, RFQ/award, PO-lifecycle+события, приход по позициям, landed/предв.себес, претензии, 4 фронт-экрана), миграция 0065, adversarial-ревью пройдено+фиксы; 82 backend+33 fe тестов; [DoD ✓review ✓tests ✓lint ✓commit ✓one-head]; эмиты для Финансов (landed_cost.calculated qty+total, claim.resolved), WMS (received по позициям), Sales (landed фасад); §2/счётчик/STATUS/sidebar — за координатором; НЕ пушено`
- - `2026-06-28 01:53` · сессия `73bd6c8c` · **КООРД:** DONE Справочники — ТЗ _tz_reference.md закрыт (12 пунктов, ~16 локальных коммитов 0da276b…82d395a) + адверсариальное ревью (11 находок, 10 исправлено). Миграции **0067** (Account/Region effective_from/to), **0070** (SKU volume_m3/vat_code + ref_sku_version) — атомарно через next_migration.py, прошу вписать в счётчик. [DoD: ✓review(workflow 17 агентов) ✓tests(pytest 95 + vitest 17) ✓lint(ruff+tsc) ✓commit(локально, не пушено) ✓migration(0067/0070, down линейны) ✓security(гейты refs.view на query+MDM-reads, модерация ставок) ✗depmap(новых межмодульных событий шины нет — §2 не трогал)]. NEEDS-ARB(low, отложено): SCD2 partial-unique индекс против гонки открытых версий — общие таблицы currency/vat/tnved, нужна координированная миграция.
- - `2026-06-28 08:07` · сессия `1b5d8576` · **КООРД:** DONE Продажи — DealHandoffOut объявлен в schemas.py + импортирован в routes.py на HEAD modules/sales=163776b (фикс пришёл коммитом 846b928 поверх f68a55d); import main зелёный, 21 PASS sales-suite. Дополнительно: fix(crm) e24e510 — FunnelTabs больше не рисует плашку «Воронки не настроены» над доской (UX-регресс на скрине оператора). Если у других полос app-import падает — их сабмодуль modules/sales на устаревшем указателе (нужно git submodule update до 163776b или текущего HEAD).`
- - `2026-06-28 08:40` · сессия `1b5d8576` · **КООРД:** DONE Продажи — fix funnels/chats SQLite-dev: сабмодуль a949ed0 (try/except OperationalError|ProgrammingError → [] + rollback), bump 4ad5fb0; 21/21 PASS sales-suite; happy-path не сломан. Правильное лечение для пользователей — пересоздать dev.db (rm dev.db + python scripts/seed.py), graceful — страховка.`
- - `2026-06-28 09:29` · сессия `1b5d8576` · **КООРД:** INFO sales — ТЗ 11/11 закрыт ЛОКАЛЬНО (sub a949ed0, super 4ad5fb0, НЕ запушено: 20 коммитов vs origin/main; мигр.0062; события sales.plan.* + sales.deal.handoff). Недоделки: (1) подборщик товара sales-deal-picker.html ждёт Gate 1 оператора; (2) datetime «Следующий шаг» в итоге звонка не реализован; (3) security-техдолг IDOR /calls/stream + BOLA /calls/{cid}/link-deal заглушены документально — ждут идентичности продавца (Keycloak P1, не моя полоса); (4) старая dev.db без funnel — graceful fallback зашит, лечение = пересоздать dev.db.
- - `2026-06-28 10:22` · сессия `ce567d7c` · **КООРД:** DONE finance — ТЗ-Р3 (`_tz_finance_r3.md`) FIN-C1+C2+A1+A2+B1+C3+C4+A3+UX1+C5 закрыты; локальные коммиты fin-7 `953aea8` (10 пунктов в submodule) и super `67d2f0e` (bump fin-7 + `core/services/onec.py:fetch_payments` + `finance-view.tsx` + 18 новых тестов); миграций нет; pytest 37 PASS (4 deselected: API-тесты падают из-за NameError в чужих полосах wms/logistics — не моё, но `create_app` не строится), ruff/tsc чисто. Подтверждаю Закупкам: `on_landed_cost` НЕ читает `stage` (только qty/total/unit) — **P4 закупок (estimated↔actual) безопасно приземляется на финансы**. Логистике: `on_freight_cost` терпит payload без `deal_id` (`leg='import'` OK). Push не делал — за оператором.

**Свежие пуши (PUSH-LOG.md):**
- - `2026-06-27 10:41` · сессия `c5a977e6` · ветка `sales-2.0-redesign` · **62b25c2** feat(coord): git-гард против amend на общей ветке + правило «своя ветка на сессию»
-   файлы: .githooks/pre-commit, .githooks/prepare-commit-msg, CLAUDE.md, scripts/coordination_hook.py

**Недавняя активность (.activity.local.md):**
- - 2026-06-28 10:20 · commit · sales-2.0-redesign 0587935 · "feat(refs): REF3-5 — гейт качества margin_blind (SKU без landed cost)" · 2 файл(ов)
- - 2026-06-28 10:21 · commit · sales-2.0-redesign 67d2f0e · "feat(finance): bump fin-7 (ТЗ-Р3) + core onec.fetch_payments + UX + tests" · 4 файл(ов)
- - 2026-06-28 10:21 ·   └ submodule modules/finance: 1 нов. коммит(ов) · 953aea8 feat(finance): ТЗ-Р3 — финконтур (10 пунктов) · ⚠ новое событие шины (обнови граф §2) | ⚠ событие добавлено, но DEPENDENCY-MAP не тронут
- - 2026-06-28 10:23 · commit · sales-2.0-redesign c509ca0 · "feat(refs): REF3-7 — стабильный контракт reference.*.changed (подписка downstream)" · 2 файл(ов)
- - 2026-06-28 10:26 · commit · sales-2.0-redesign 4330a83 · "feat(refs): REF3-8 — запись SCD2-версии SKU при правке мастер-полей" · 2 файл(ов) · ⚠ новое событие шины (обнови граф §2) | ⚠ событие добавлено, но DEPENDENCY-MAP не тронут
- - 2026-06-28 10:28 · commit · sales-2.0-redesign 4d6f718 · "feat(refs): REF3-9 — read-only dry-run проба моста кэш 1С → MDM" · 3 файл(ов)

<!-- /COORD:AUTO -->
