# G07P: локальная проверка standalone frontend под systemd

24.09.2026. Точный standalone-архив `1fd4e081` (19 653 244 байта,
SHA-256 `29bb7e29d7679da59c03dbb39e6295337789d5f12dac6c67c4919422eb6aea02`)
содержит 3220 безопасных имён и `BUILD_ID=NugLquCeWhonBTHKU0uZf`.
Для локальной репетиции read-only скопирован исполняемый Node с рабочего
сервера: v22.22.3, SHA-256
`e6ec2c188d83d813f81f2de8aea084d74dce603ac1abedd0a30ad941b10087b2`.
Серверный файл и сервис не менялись.

Скрипт [accounting_frontend_systemd_rehearsal.sh](../../../scripts/accounting_frontend_systemd_rehearsal.sh)
ограничен локальной WSL: он сверяет оба SHA-256, распаковывает архив в
одноразовый `/run`-каталог, сверяет версию Node и BUILD_ID, проверяет unit
через `systemd-analyze verify`, запускает отдельный transient service с
DynamicUser, ProtectSystem и localhost-only доступом. Backend URL
направлен на неработающий локальный порт; ни рабочий backend, ни БД не
использовались. Первая попытка обнаружила ошибку тестовой среды:
`PrivateTmp=yes` скрывал исполняемый файл в `/tmp`. Скрипт исправлен на
одноразовый каталог `/run` и повторно запущен.

**Итог повторной проверки: PASS.** WSL systemd 259 запустил точный
Node v22.22.3; resolved ExecStart и WorkingDirectory совпали с
кандидатом. Анонимный GET `/erp/accounting` вернул HTTP 307, запрос
статического JS — HTTP 200. Прослушивание было только на
`127.0.0.1:13100`. После `systemctl stop` временный unit, каталог и
слушатель отсутствовали. `bash -n`, TypeScript и 8 целевых UI-тестов
экрана обзора правил бухгалтера прошли в текущем исходнике.

Эта проверка показывает локальный запуск и остановку **кандидата** под
systemd, но не проверяет реальный `cmr-frontend.service`, порядок его
drop-in, Caddy, OIDC-вход бухгалтера, backend/API или совместимость
возврата после миграции БД. Production-switch и реальный rollback не
выполнялись; смешанный выпуск остаётся **NO-GO**.
