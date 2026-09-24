# G07P: локальная проверка сборки кандидата, 24.09.2026

Кандидат: `agent/crm-acc-prod009` @ `8e3f2bbc9fdca0188be6ba2914f90e2df66e29f9`, Alembic head `0176`. Это проверка изолированного рабочего дерева на Windows, а не пакет для сервера или подтверждение работы пользователя.

| Проверка | Результат | Граница вывода |
| --- | --- | --- |
| `frontend: npm run build` | PASS после повторного запуска вне sandbox из-за `spawn EPERM`; Next.js 15.5.19 скомпилировал приложение и сгенерировал 137 статических страниц. | Сборка шла без production OIDC-настроек; предупреждения ESLint не блокировали Next. Полученные файлы `.next` не являются готовым серверным пакетом. |
| `frontend: npm run build:production` | Ожидаемый отказ: `NEXT_PUBLIC_AUTH_MODE must be oidc`, отсутствуют `NEXT_PUBLIC_KEYCLOAK_ISSUER` и `NEXT_PUBLIC_KEYCLOAK_CLIENT_ID`. | Не подставлялись вымышленные или серверные секреты; production-артефакт не создан. |
| `python -m compileall -q config core modules` | PASS. | Синтаксис Python проверен; это не сборка Docker-образа и не интеграционный прогон. |
| `docker version --format '{{.Server.Version}}'` | FAIL: локальный Docker API `dockerDesktopLinuxEngine` недоступен. | Backend image здесь не собран. |

Чистый исходник также не воспроизводится из текущего GitHub: [точный манифест](PILOT-RELEASE-SOURCE-2026-09-24.md) фиксирует шесть недоступных gitlink SHA и отсутствующий root SHA. Подтверждённый серверный baseline на 24.09.2026 06:30 UTC — схема `0116`; локальный кандидат `0176`. Синтетическая репетиция перехода записана отдельно, но восстановление копии реальной базы, production-конфигурация, frontend-пакет и пользовательский сценарий не подтверждены. Никаких изменений сервера, push, merge или deploy при этой проверке не было.
