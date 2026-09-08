# microchips.by CRM intake producer

Этот каталог содержит минимальный native PHP 8.2 producer для восьми целевых
Bitrix form results microchips.by и новых sale orders. Код не регистрирует
события самостоятельно: подключение к production hook и отключение старого
Aios hook выполняются оператором после приёмки receiver contract.

Поддерживаются формы `1, 2, 3, 4, 5, 6, 9, 10`. Формы `7, 8, 11` намеренно
исключены. Источник формы получает identity `form:FORM_ID:result:RESULT_ID`.
Новый order получает identity `order:ORDER_ID`; событие с `IS_NEW=false`
игнорируется. Для каждого identity `delivery_id` равен `source_id` с первого
spool write и не меняется на повторных POST.

## Контракт доставки

POST всегда идёт на фиксированный
`https://belakb.by/integrations/intake/v1` с заголовком
`X-Intake-Token`. Token загружается только из закрытого config файла и не
попадает в JSON очереди, status files или сообщения consumer. JSON содержит:

```json
{
  "namespace": "microchips.by",
  "source_id": "form:1:result:123",
  "delivery_id": "form:1:result:123",
  "lead": {
    "name": "...",
    "company": "...",
    "phone": "...",
    "email": "...",
    "region": "...",
    "product": "...",
    "message": "...",
    "utm_source": "...",
    "utm_medium": "...",
    "utm_campaign": "...",
    "landing_url": "..."
  },
  "source_url": "https://microchips.by/form"
}
```

Receiver limits are `name/company<=255`, `phone<=64`, `email<=128`,
`region<=64`, UTM values `<=128`, `product<=128`, `message<=256 KiB`, and
URLs `<=2048` bytes. Полное исходное событие сохраняется в закрытом
`raw_source` envelope. Любое превышение лимита получает `failed_review`:
ограниченная строка не отправляется как будто она полна. В текущих восьми
формах file fields не обнаружены. Любые обнаруженные files, включая files
order, также получают `failed_review`: raw envelope сохраняется и HTTP не
выполняется до ручного решения.

Для form answers `lead.message` состоит из основного сообщения и всех
непустых дополнительных ответов в формате `SID: value`; известные aliases
контактных и служебных полей исключаются. Общий лимит применяется после
объединения, а превышение оставляет исходные answers в `raw_source` и требует
review.

Ответ receiver принимается только с теми же `namespace`,
`identity_namespace`, `source_id`, `delivery_id` и `payload_sha256`. В envelope
`wire_sha256` — digest неизменяемых байтов `request_json`, а `payload_sha256` —
canonical digest после G04 `IntakeRequestIn`/`_prepare`: все default-поля,
`phone`/`email` cleanup, сортировка объектов и `ensure_ascii=True` входят в
расчёт. Поэтому producer не сравнивает receipt с SHA сырого wire JSON.
`queued` означает только подтверждение очереди receiver и записывается как
`queued`; envelope остаётся в `pending` и получает bounded `next_retry_at` для
повторного immutable POST. Ошибкой queued не считается. Producer не называет
это доставленным лидом. Для `delivered` нужны
положительный integer `lead_id`, полное совпадение количества ожидаемых files,
SHA каждого файла и положительный `attachment_id`. Ответ `delivered` после
POST считается промежуточным: producer обязательно делает GET receipt и
перемещает envelope в `done` только после GET со статусом `delivered` и теми же
identity/hash/file checks. `failed`, `unavailable` и любой сбой GET остаются в
pending с временем следующей попытки. Один immutable `request_json`
используется для каждого retry, поэтому receiver получает тот же body и тот же
delivery ID.

GET receipt реализован функцией `microchipsCrmIntakeGetReceipt($receiptId,
$token, $transport[, $sourceId, $payloadHash, $expectedFiles])` и использует тот же header:
`GET /integrations/intake/v1/receipts/{receipt_id}`.

## Файлы и права

На server config и spool должны быть вне webroot:

```php
<?php
return [
    'token' => 'EXISTING_TOKEN_FROM_OPERATOR',
    'spool_dir' => '/var/lib/microchips-crm-intake',
];
```

Рекомендуемая подготовка под root/deploy account:

```sh
install -d -m 0700 /etc/microchips-crm-intake
install -m 0600 /path/to/config.php /etc/microchips-crm-intake/config.php
install -d -m 0700 /var/lib/microchips-crm-intake
```

`microchipsCrmIntakeLoadConfig()` повторно проверяет абсолютный путь и закрытые
права на Linux и отвергает symlink в config, spool и его подпапках. Producer создаёт `pending`, `done`, `failed`, `review`,
`status` с mode 0700, а envelopes/status/locks — mode 0600. Disk-full,
filesystem outage и резервное копирование spool остаются отдельной ops
обязанностью: код делает ошибку видимой, но не обещает невозможную гарантию
записи при заполненном диске.

На Linux запись envelope/status выполняет `fflush` + `fsync` файла и `fsync`
каталога после публикации или перемещения. Отказ любого sync — fail-closed:
операция не возвращает успех, а уже опубликованный pending source остаётся
видимым для recovery. На Windows directory fsync недоступен в native PHP,
поэтому локальные тесты используют ограниченную injectable проверку; production
target — Linux PHP 8.2. Перемещение между state directories сначала создаёт
hard-link и синхронизирует target directory, поэтому отказ этой синхронизации
сохраняет имя в `pending` для retry.

## Bitrix boundaries

Для form hook используется:

```php
require_once '/path/to/microchips_crm_intake.php';

microchipsCrmIntakeOnAfterResultAdd(
    $WEB_FORM_ID,
    $RESULT_ID,
    null,
    ['config_path' => '/etc/microchips-crm-intake/config.php']
);
```

При `null` loader код вызывает существующий native
`CFormResult::GetDataByID($resultId, [], $result, $answers)`. Existing
`microchipsAiosFirstAnswer()` и `microchipsAiosMessage()` не изменяются и не
являются частью новой durable boundary. При необходимости mapping SID-ов
передаётся через `field_map`/значения в options.

Для `OnSaleOrderSaved` этот worktree не содержит локального Bitrix vendor
source, поэтому producer не выдумывает регистрацию события или методы
entity. Оператор должен подтвердить в установленном vendor source, что
`ENTITY` и `IS_NEW` действительно доступны, затем передать их в:

```php
microchipsCrmIntakeOnSaleOrderSaved(
    ['ENTITY' => $entity, 'IS_NEW' => $isNew],
    [
        'config_path' => '/etc/microchips-crm-intake/config.php',
        'snapshotter' => static function ($entity): array {
            // Use the locally verified Bitrix API here. Do not mutate the order.
            return $verifiedSnapshot;
        },
    ]
);
```

Snapshot must capture order ID, customer, contact, properties, products with
quantities and prices/totals, delivery, comment, UTM/source URL and any file
metadata. The producer only reads the entity; it never edits the order and
never invokes payment.

The legacy Aios event hook remains active until the primary operator performs
the cutover. At cutover, disable only that legacy Aios hook, preserve the
Bitrix24 hook, and check that no two producer hooks are active for one result.

## Single consumer

The consumer takes an exclusive non-blocking `flock` on `.consumer.lock`; a
second process exits busy. It sends each pending envelope at most once per
run. Queued receipts, failed/unavailable responses and transport errors remain
visible in `pending` and in a 0600 status file, with bounded exponential retry
delay. Only a GET-confirmed `delivered` receipt moves the original envelope to
`done` for recovery and audit.

Run the staged consumer only after config and receiver acceptance:

```sh
php /path/to/microchips_crm_intake.php consume \
  --config /etc/microchips-crm-intake/config.php --limit=100
```

`--force` is for an operator retry when investigating a delayed item. The CLI
prints only identity/state/error summaries; it does not print token or request
body. A non-zero exit means lock contention, config/transport error, or a
pending delivery error requiring attention.

## Local verification

Tests do not call the site, receiver, Bitrix, CRM or network. They use an
injected transport and array snapshots to verify source identities, G04 golden
canonical hashes (separate from wire SHA), immutable body retries, queue
acknowledgement, failure retention, mandatory GET after POST `delivered`,
positive lead/file receipt validation, order capture and review routing for
files:

```sh
php -l ops/intake/microchips_crm_intake.php
php -l ops/intake/test_microchips_crm_intake.php
php ops/intake/test_microchips_crm_intake.php
```

The staged test directory can be copied to a PHP 8.2 server for the same CLI
run. The production cURL transport requires the server's PHP cURL extension;
the test transport is a mock and does not require network access.

## Rollback and source recovery

Before cutover, the primary operator records the current legacy handler and
hook fingerprints plus a restorable source backup. To roll back, stop the
consumer, disable only the new producer hook, restore the recorded legacy hook
from that verified backup, and leave `pending`, `done` and `review` intact.
Do not delete the spool during rollback. After the cause is fixed, the same
immutable envelopes can be replayed with the same delivery IDs; inspect the
receiver receipt before replaying any item already marked `queued` or
`delivered`.

Full recovery requires a copy of the complete spool directory, its status
files, config backup held separately, source fingerprint, and the operator's
last consumer run output. The script retains source envelopes, but it cannot
create a backup while storage is unavailable and does not solve disk-full
conditions by itself.
