# Трасса sale → procurement → shipment

Статусы отражают только доступные локальные доказательства. «Предварительный резерв» — обещание/ожидание для клиента; «физический резерв склада» — резерв конкретного остатка. Они не взаимозаменяемы.

| Переход | Trigger и предусловия | ID / граница владения | Локальный путь и доказательство | Статус |
| --- | --- | --- | --- | --- |
| Сделка → счёт/квота → резерв | Выпуск документа с выбранным режимом резерва | deal/document ID; организация документа | [test_invoice_issuance.py](../../tests/test_invoice_issuance.py), [test_invoice_reserve_mode.py](../../tests/test_invoice_reserve_mode.py) | IMPLEMENTED (тестовое доказательство) |
| Дефицит → закупка | Недостаток по товару для спроса сделки | deal demand, организация, SKU | [test_deal_procurement_demands_postgres.py](../../tests/integration/test_deal_procurement_demands_postgres.py), [test_procurement_deficit.py](../../tests/test_procurement_deficit.py) | IMPLEMENTED (тестовое доказательство) |
| Предварительное распределение / свободный остаток | Заказ поставщику ещё не стал физическим приходом | ожидаемый резерв ≠ физический резерв | [test_expected_reservations_postgres.py](../../tests/integration/test_expected_reservations_postgres.py), [test_invoice_on_order.py](../../tests/test_invoice_on_order.py) | IMPLEMENTED (тестовое доказательство) |
| Приход поставщика → физический остаток/резерв | Подтверждённый приход с привязкой к организации | supplier receipt, склад, SKU, партия | [test_procurement_receipt_drafts.py](../../tests/accounting/test_procurement_receipt_drafts.py), [test_stock_reservation_lock_postgres.py](../../tests/integration/test_stock_reservation_lock_postgres.py) | IMPLEMENTED (тестовое доказательство) |
| ТН/ТТН/отгрузка → списание физического резерва | Физическая отгрузка по счёту; только доступный физический резерв | invoice/document, shipment, организация | [test_invoice_physical_shipments.py](../../tests/test_invoice_physical_shipments.py), [test_invoice_remainder.py](../../tests/test_invoice_remainder.py) | IMPLEMENTED (тестовое доказательство) |
| Потеря сделки / отмена счёта → release | Отмена допускается по состоянию документа и резерва | deal/document/reservation ID, организация | [test_deal_loss.py](../../tests/test_deal_loss.py), [test_invoice_cancellation.py](../../tests/test_invoice_cancellation.py), [test_invoice_reservation_release.py](../../tests/test_invoice_reservation_release.py) | IMPLEMENTED (тестовое доказательство) |
| Оплаченный счёт → отмена только после refund | Оплата блокирует отмену до подтверждённого возврата | invoice/payment/refund ID, организация | [test_document_payment_lock_postgres.py](../../tests/integration/test_document_payment_lock_postgres.py), [test_invoice_cancellation_postgres.py](../../tests/test_invoice_cancellation_postgres.py) | IMPLEMENTED (тестовое доказательство) |
| Реестр документов клиента / drill-down первички | Карточка сделки с org+invoice query | deal ID, organization ID, invoice ID | [frontend deal page](../../frontend/src/app/crm/deals/[id]/page.tsx), [test_client_document_register.py](../../tests/accounting/test_client_document_register.py), [test_document_original_postgres.py](../../tests/integration/test_document_original_postgres.py) | IMPLEMENTED (маршрут и тесты) |
| Уведомление клиента о release/cancel | Доставка уведомления, канал, receipt | клиент/канал/message ID | [test_invoice_notifications.py](../../tests/test_invoice_notifications.py) | UNKNOWN: наличие теста не подтверждает доставку во внешний канал |

## Исполнимая приёмка

1. Выпустить счёт по сделке с явным режимом резерва; записать ID сделки, документа, организации и SKU.
2. При дефиците создать спрос закупки и отдельно проверить предварительное распределение и свободный остаток.
3. Подтвердить приход поставщика; сверить физический складской резерв с SKU/партией и организацией.
4. Оформить физическую отгрузку с ТН/ТТН; проверить уменьшение именно физического резерва и наличие source-document drill-down.
5. Проверить release при потере сделки/отмене. Для оплаченного счёта сначала подтвердить refund; отмена до него должна быть отклонена.
6. Зафиксировать UNKNOWN по внешней доставке уведомления и юридической корректности формы до отдельного доказательства.

## Подтверждённые пробелы и следующий срез

Проверяемый GAP в доступных файлах не установлен. Единственный безопасный следующий срез: добавить сквозной acceptance-test, который фиксирует в одном сценарии IDs сделки, demand, supplier receipt, физического резерва и shipment; он не должен заявлять доставку уведомления или юридическую корректность ТН/ТТН.
