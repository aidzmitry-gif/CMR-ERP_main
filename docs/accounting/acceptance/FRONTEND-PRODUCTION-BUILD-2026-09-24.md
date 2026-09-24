# G07P: локальная production-сборка интерфейса

Дата: 24.09.2026. Исходник `agent/crm-acc-prod009` @ `45b7217f28f98fdc18651312a1eb113f1556c9ec`; tracked frontend не изменялся до/после сборки. Действующий на сервере `cmr-frontend.service` по-прежнему запускает `/opt/cmr-erp-releases/crm-ready-r4-ui-20260916/frontend` на порту 3100; его переключение не выполнялось.

Выполнено `npm run build:production` с публичными параметрами действующего сервиса: `NEXT_PUBLIC_AUTH_MODE=oidc`, `NEXT_PUBLIC_KEYCLOAK_ISSUER=https://auth.belakb.by/realms/aios`, `NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=aios-backend`, `NEXT_PUBLIC_APP_ORIGIN=https://belakb.by`. Остальные переменные/секреты сервиса не считывались. Обёртка проверила эти значения; Next.js 15.5.19 успешно скомпилировал приложение, сгенерировал 137 статических страниц и записал `BUILD_ID=5QKcqnD-7jz-fERaY9TiI` (SHA-256 файла `89d597eee3daee3a5dfcc1959b53cfc8fb493f44af0eddc81f3f37cf071d4f65`). Публичные issuer и client ID присутствуют в локальных статических JS-бандлах. Предупреждения ESLint не прервали сборку.

Артефакт `.next` остался только в локальном игнорируемом каталоге. Пакет для серверного запуска, точка возврата, OIDC вход пользователя и бухгалтерский сценарий в работающем приложении не проверены. Это **сборка**, а не deployment или разрешение на переход с 1С.
