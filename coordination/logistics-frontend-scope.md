# logistics-frontend — scope

## Задача (уровень 2: касаемые файлы + верификация)

Собрать страницу `erp/logistics` с вкладками Доставка/Тарифы/Парк/Тендер/Scorecard/Аудит
поверх существующего `/logistics/*` API. Проверка: `npx vitest run src/lib/logistics-*.test.ts`
зелёный + `npm run lint` чистый по тронутым файлам. Подробное ТЗ — в first-msg.

## LOOP CONTRACT

```yaml
scope:
  include:
    - frontend/src/app/erp/logistics/**
    - frontend/src/components/erp/logistics-*.tsx
    - frontend/src/lib/logistics-*.ts
  exclude:
    - frontend/src/lib/api.ts
    - frontend/src/lib/types.ts
    - frontend/src/lib/format.ts          # читать можно; менять нельзя (общий)
    - frontend/src/lib/funnel-configs.ts
    - frontend/src/components/funnel/**
    - frontend/src/components/sidebar.tsx
    - frontend/src/app/erp/office/**       # чужой воркер
    - frontend/src/app/erp/crypto/**       # ломает build, не трогать
    - modules/**                           # сабмодуль/бэкенд — недоступен и вне скоупа
    - migrations/**
    - "**/*.py"
permissions:
  repo: write-branch
  db: none
  llm: enabled
budget:
  max_iterations: 6
  max_runtime_minutes: 45
  max_files_changed: 12
  max_consecutive_test_failures: 3
stop:
  - same_failure_seen_twice
  - file_touched_outside_scope
  - need_to_modify_shared_file        # api.ts/format.ts/funnel/sidebar → NEEDS-ORCHESTRATOR-ANSWER
  - product_behavior_ambiguous
report:
  destination: coordination/logistics-frontend-status.md
```

## Acceptance gate

- [ ] Чистая логика в `lib/logistics-*.ts` покрыта co-located vitest, был RED до реализации (TDD)
- [ ] `npx vitest run src/lib/logistics-*.test.ts` → 0 фейлов
- [ ] `npm run lint` — нет новых ошибок в тронутых файлах
- [ ] `erp/logistics` рендерит 6 вкладок; при пустом/лежащем backend не падает (graceful fallback)
- [ ] Деньги выводятся в BYN (`formatByn`), не в ₽
- [ ] НЕ запускался `npm run build` (известно сломан вне скоупа); проверка через vitest+lint
- [ ] Тронуты только include-файлы; шина/бэкенд/миграции не тронуты
- [ ] Six-layer в теле коммита; status-файл заканчивается `STATE: COMPLETE`

## Anticipated failure modes
- Хочется поправить общий `FunnelBoard`/`format.ts`/`api.ts` под вкладку (Class A — wiring):
  НЕ делай — вынеси своё в `components/erp/logistics-*` и `lib/logistics-*`; если правда
  нужен общий файл — STOP, `NEEDS-ORCHESTRATOR-ANSWER`.
- Попытка дёрнуть backend, которого нет в worktree (сабмодуль не выкачан) — не нужен:
  верификация через vitest на чистой логике + рендер с fallback.
- `npm run build` падает на `crypto/page.tsx` (Class D, чужой файл) — не гейтись на build.

## API-контракт `/logistics/*` (backend готов; клиент — через `/api/logistics/*`)

Деньги во всех ответах — BYN. Списки пусты до сидирования (есть `*/seed`).

**Доставка / дашборд**
- `GET /logistics/shipments` → ShipmentOut[]: `{id,number,customer,address,route_from,route_to,carrier,carrier_code,cargo,weight_kg,amount,status,tracking_status,eta}`
- `GET /logistics/board` → FunnelBoardOut (воронка; формат — см. `components/funnel/funnel-board.tsx`)
- `GET /logistics/dashboard` → `{in_transit,delivery_in_transit,import_in_transit,at_customs,delivered_total,avg_delivery_days,on_time_pct,logistics_cost,shipping_cost_company,carriers[],cost_by_carrier[]}`
- `GET /logistics/costs` → `{total,company,client,import_cost,by_carrier:[{carrier,shipments,cost}]}`

**Тарифы / зоны**
- `GET /logistics/zones` → `[{id,code,name,coverage,cities[],sla_days_min,sla_days_max}]`
- `POST /logistics/zones/seed` → ZoneOut[]
- `GET /logistics/carrier-tariffs?zone=z2` → `[{carrier_code,zone_code,price_w5,price_w10,price_w30,over30_per_kg,pickup_fee,cod_pct,insurance_pct,effective_from}]`
- `POST /logistics/carrier-tariffs/seed` → CarrierTariffOut[]

**Перевозчики / парк / допуски**
- `GET /logistics/carriers` → `[{id,name,code,kind,mode,on_time_pct,avg_days,shipments_count,active}]`
- `GET /logistics/carriers/catalog` → `[{code,name,kind,mode,integration,track_url}]`
- `POST /logistics/carriers/seed` → CarrierOut[]
- `GET /logistics/carriers/{code}/vehicles` → `[{vehicle_class,capacity_kg,volume_m3,temp_control,count}]`
- `GET /logistics/carriers/{code}/cargo-capabilities` → `[{category,adr,oversize,max_weight_kg,max_dim_cm}]`
- `POST /logistics/fleet/seed` → `{...}`
- `GET /logistics/carriers/eligible?weight_kg=&category=&needs_temp=&max_dim_cm=&adr=` → `[{carrier_code,carrier,vehicle_class,capacity_kg}]`

**Scorecard**
- `GET /logistics/carriers/scorecard?period=2026-06` → `[{carrier_code,period,otd_pct,otif_pct,damage_free_pct,billing_accuracy_pct,claims_ratio_pct,cost_per_delivery,shipments,score,grade}]` (grade ∈ A/B/C)
- `POST /logistics/carriers/scorecard/seed` → ScorecardOut[]

**Аудит счетов**
- `GET /logistics/costs/audit?period=` → `{period,checked,discrepancies,to_recover,items:[{id,shipment_code,carrier_code,invoice_amount,expected_amount,variance,reason,status}]}`
- `POST /logistics/costs/audit/seed` → AuditEntryOut[]

**Тендер (RFQ)**
- `GET /logistics/rfqs` → `[{id,number,cargo,weight_kg,category,route_from,route_to,zone_code,status,office_doc_ref,created_by,deadline,awarded_carrier_code,awarded_price,shipment_id}]`
- `GET /logistics/rfqs/board` → FunnelBoardOut
- `GET /logistics/rfqs/{id}` → RfqOut
- `GET /logistics/rfqs/{id}/invites` → `[{id,rfq_id,carrier_code,channel,status}]`
- `GET /logistics/rfqs/{id}/bids` → `[{id,rfq_id,carrier_code,carrier,price,eta_days,vehicle_class,valid_until,comment,round,is_best}]`
- `POST /logistics/rfqs/{id}/broadcast` → `{rfq_id,status,invited,carriers[]}`
- `POST /logistics/rfqs/{id}/bids` body `{carrier_code,price,eta_days,vehicle_class,valid_until,comment}` → BidOut
- `POST /logistics/rfqs/{id}/negotiate` body `{carrier_code,new_price,comment}` → BidOut
- `POST /logistics/rfqs/{id}/award` body `{carrier_code?}` → `{rfq_id,status,carrier_code,carrier,price,shipment_id,shipment_number}`
- `POST /logistics/rfqs/seed` → RfqOut (демо-тендер с приглашениями и ставками)
- `POST /logistics/rfqs` body RfqCreate `{cargo,weight_kg,category,route_from,route_to,zone_code,...}` → RfqOut

Статусы тендера: `draft → sent → collecting → negotiation → awarded → contracted`.
