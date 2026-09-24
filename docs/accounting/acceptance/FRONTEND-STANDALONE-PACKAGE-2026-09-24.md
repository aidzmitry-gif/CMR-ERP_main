# G07P: локальный Linux-пакет frontend для пилота

Дата: 24.09.2026. Исходник `agent/crm-acc-prod009` @
`1fd4e0811eceee41681a5cac3da99cdfcf36a245` материализован только из
Git-объектов: 2363 файла корня и 250 файлов десяти закреплённых gitlink,
каждый blob проверен по своему Git SHA-1. Незатреканные отчёты не вошли.

`frontend/next.config.mjs` включает стандартный Next.js 15
[`output: "standalone"`](https://nextjs.org/docs/15/app/api-reference/config/next-config-js/output).
`frontend/Dockerfile.runtime` фиксирует Linux/amd64 Node 22.23.3 base
`node@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c`.
Сборка из чистого дерева выполнила `npm ci` и `npm run build:production` с
четырьмя публичными значениями: `NEXT_PUBLIC_AUTH_MODE=oidc`,
`NEXT_PUBLIC_KEYCLOAK_ISSUER=https://auth.belakb.by/realms/aios`,
`NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=aios-backend`,
`NEXT_PUBLIC_APP_ORIGIN=https://belakb.by`. Секретные настройки и данные
production в сборку не передавались. Статические файлы включены в runtime.

| Проверка | Результат |
| --- | --- |
| Linux/amd64 image ID | `sha256:cf25ac8862b04c56865729418f6ed20ee8b10cbc786d8cb11c8fe8919d09a15e` |
| OCI revision label | `1fd4e0811eceee41681a5cac3da99cdfcf36a245` |
| `.next/BUILD_ID` в runtime | `NugLquCeWhonBTHKU0uZf` |
| Локальный Docker tar | `.harness/artifacts/CRM-ACC-001/frontend-runtime-1fd4e081.tar`, 99 745 792 байта |
| SHA-256 tar | `02d6dadd86fbe4453ee0b570ada98ffd62cd18994ac79253aef8f6d2f94b63d1` |
| Проверка архива | `docker load` восстановил тот же image ID и revision label |
| Состав runtime | 2582 файла; `server.js`, BUILD_ID и `.next/static` есть, файлов `.env*` нет |
| Изолированный запуск | `--network none --read-only --tmpfs /tmp`; Next.js 15.5.19 сообщил Ready |
| HTTP без входа | `/erp/accounting` и `/erp/spravochniki/accounts` перенаправили на `/login?error=session_expired`; один `/_next/static/chunks/*.js` вернул 200 `application/javascript` |

Пакет создан и проверен **только локально**. Текущий серверный
`cmr-frontend.service` не переключался. Этот Docker-образ не является готовой
командой выпуска для существующего systemd frontend: смешанный маршрут с
миграцией и интерфейсом остаётся по
`ops/belakb-deploy/START-HERE.md`. Требуются отдельные проверка совместимости
runtime-конфигурации и точки возврата, авторизованный OIDC-вход и
пользовательский бухгалтерский сценарий. Проверка HTTP без входа не
подтверждает работу страницы после авторизации или отказ от 1С. На момент
первичной сборки GitHub push был остановлен автоматической проверкой;
последующее разрешение и публикация описаны ниже.

## Дополнительный runtime-архив для systemd

После явного разрешения пользователя на GitHub-публикацию точных репозиториев
и SHA исходная branch и все 10 gitlink воспроизведены из GitHub. Из **того же
уже проверенного** Linux-образа экспортирована только `/app` в
`.harness/artifacts/CRM-ACC-001/frontend-standalone-1fd4e081.tar.gz`:
19 653 244 байта, SHA-256
`29bb7e29d7679da59c03dbb39e6295337789d5f12dac6c67c4919422eb6aea02`.
Архив содержит `server.js`, `.next/BUILD_ID`, 319 путей `.next/static/*` и
не содержит `.env*`.

Архив распакован в **новом** Linux Node 22.23.3 контейнере с `--network none`,
read-only root и временным `/tmp`, без исходников/`node_modules` рабочего
каталога. `node server.js` сообщил Ready; `BUILD_ID` после распаковки равен
`NugLquCeWhonBTHKU0uZf`. Один статический JS вернул 200, а анонимный
`/erp/accounting` перешёл на `/login?error=session_expired`. Временный
контейнер удалён. Это доказывает переносимость файлового runtime в указанной
Linux/Node среде. Read-only сверка сервера 24.09.2026, 08:34 UTC показала:
`/usr/bin/node` v22.22.3, ABI 127; действующий `cmr-frontend.service` активен
и запускает `node_modules/.bin/next start -p 3100` из
`/opt/cmr-erp-releases/crm-ready-r4-ui-20260916/frontend`, BUILD_ID
`F_-CH9cdxitoaicSnuYyR`. Локальная проверка архива шла на Node 22.23.3;
совместимость с точной серверной patch-версией, systemd switch и rollback
ещё не проверены. Оба архива остались локальными; на сервер ничего не
отправлялось.
