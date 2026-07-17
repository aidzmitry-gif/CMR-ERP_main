# OIDC flip readiness (2026-07-17)

> **Не флипать** `AIOS_AUTH_MODE=oidc` / `AIOS_ENVIRONMENT=prod`, пока не закрыт ручной смоук SSO ниже.

## Уже зелёное

| Проверка | Результат |
|----------|-----------|
| Issuer | `https://auth.belakb.by/realms/aios` openid **200** |
| Token (password grant, user `dima`) | `iss`/`aud` (`aios-backend`) / `realm_access.roles` ⊇ `director` |
| FE OIDC start | `307` → Keycloak authorize (PKCE) |
| FE callback routes | `/api/auth/oidc/callback` в билде |
| Proxy Bearer | `api-proxy-headers` + `TOKEN_COOKIE` |
| SSR Bearer (CRM) | deals/leads/owner передают `accessToken` (`0a8f7d8`, FE rebuild) |
| App runtime | всё ещё `AIOS_AUTH_MODE=dev` (Bearer alone → Гость — ожидаемо) |
| FE proxy + cookie | `Cookie: aios_access_token=<jwt>` → `/api/sales/board` **200**, 11 stages |
| PKCE E2E (local FE) | start→KC login→callback cookies→board **200**→logout (после `/etc/hosts` hairpin fix) |
| Silent refresh | `POST /api/auth/oidc/refresh` + middleware (pages) + API proxy; smoke **200** + board |
| Hairpin | `127.0.0.1 auth.belakb.by` в `/etc/hosts`; иначе token exchange `ECONNREFUSED 93.125.0.131:443` |

## Остатки до комфортного флипа

- ~~**Silent refresh**~~ — middleware + `/api/[...path]` + `POST /api/auth/oidc/refresh` (`aios_refresh_token`).
- **Браузер через Caddy:** нужен Basic Auth (`dima` / пароль Caddy) + кнопка Keycloak; автосмоук идёт через `:3100` в обход Caddy.
- Пароль Keycloak-пользователя `dima` — **сменить** после смоука.

## Ручной смоук перед флипом

1. Открыть `https://belakb.by/login` (Basic Auth Caddy + dev picker).
2. Нажать **«Войти через Keycloak»** → логин `dima` / пароль (сменить после первого входа).
3. Вернуться на `/crm/deals` с cookie `aios_access_token` + `aios_user` + `aios_role`.
4. DevTools → Application → Cookies: есть `aios_access_token`.
5. Только после этого — флип (см. `secure-env-prep.md`):
   - `AIOS_AUTH_MODE=oidc`
   - `AIOS_ENVIRONMENT=prod` (+ сильный DB pass, если ещё не)
   - recreate **app**
   - `NEXT_PUBLIC_AUTH_MODE=oidc` + rebuild frontend
6. Смоук: login только через KC; `/sales/board` с Bearer **без** `X-User-Roles` → 200 и роли из JWT.

## Тестовый пользователь Keycloak

- username: `dima`
- realm role: `director`
- VERIFY_PROFILE на realm отключён (иначе `Account is not fully set up`)
- Пароль задавался при создании — **сменить** в админке Keycloak
