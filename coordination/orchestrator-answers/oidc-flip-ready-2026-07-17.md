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
| SSR Bearer (CRM) | deals/leads board+detail передают `accessToken` |
| App runtime | всё ещё `AIOS_AUTH_MODE=dev` (Bearer alone → Гость — ожидаемо) |

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
