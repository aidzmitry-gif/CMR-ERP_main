# Прямой приём заявок CRM-INTAKE-001

Backend добавляет `/integrations/intake/v1` и квитанции доставки. Прямые
источники сохраняют неизменяемый запрос до POST; после повторов только GET
`delivered` с совпадающими идентификаторами, canonical SHA256, lead_id и
метаданными файлов подтверждает доставку. `queued` не является созданным лидом.

Состав:

- `microchips_crm_intake.php` — PHP 8.2 очередь форм и новых заказов;
  `microchips_bitrix_hooks.php` — native Bitrix регистрация и read-only snapshot
  заказа, проверенные по установленному vendor API. Подробности в
  `README-microchips.md`. Само включение файла не регистрирует hooks: требуется
  явный вызов `microchipsCrmIntakeRegisterNativeHooks()` после загрузки producer.
- `mottor_receipts.py` — новый worker enersys.by. Использует очередь и collector
  `mottor_bridge.py`, сохраняет legacy accepted/uncertain без автоматического
  повтора. Порядок переключения в `MOTTOR-RUNBOOK.md`.
- `mail_delivery.py` — IMAP readonly, MIME staging, отбор и доставка с receipt.
  Конфигурация и ограничения в `MAIL-RUNBOOK.md`.
- `mail_receipts.py` — conservative parser: обычный внешний клиент, адресованный
  на `To: order@microchips.by`, проходит по intent/file checks; site-copy review требует provenance от
  `microchips.by`/`lpmotor.ru` или явного form/Mottor/RS marker. Email не является
  ключом связывания. `application/msword`/`.doc` сохраняется байт-в-байт в тех же
  пределах; выдача скачивает его как attachment с `nosniff`.

Проверка ops-кода:

```sh
cd ops/intake
python -B -m unittest -v test_mail_stage test_mail_receipts test_mail_delivery test_mottor_bridge test_mottor_receipts test_receipt_queue
php test_microchips_crm_intake.php
```

Python: 55 синтетических проверок. PHP протестирован на серверном PHP 8.2;
его настоящий envelope прошёл ASGI receiver/outbox и повторную доставку с одним
лидом. Полученный receipt принят PHP-валидатором. Эталонный JSON нормализации
получен из реального receiver, не из имитации producer.

Включение production не выполняется установкой этого каталога. До переключения
нужны интеграция backend и миграция, приватные конфигурации/очереди вне webroot,
один worker на очередь, сверка source→lead и проверка восстановления. При
переключении microchips отключается только legacy hook собственной CRM;
существующее подключение Bitrix24 сохраняется.

Незавершённая приёмка: пароль приложения admin@enersys.by, реальные примеры трёх
шаблонов Legat и копий сайта, все различающиеся формы/корзина microchips,
периодические workers и видимые оператору ошибки. Закупки, копии сайта и
неподдерживаемые письма сохраняются для review, не объявляются доставленными.
Служебные письма Legat не превращаются в тендерные лиды.
