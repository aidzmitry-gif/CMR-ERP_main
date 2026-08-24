#!/usr/bin/env python3
"""OIDC PKCE smoke against local FE + Keycloak (bypass Caddy Basic Auth)."""

from __future__ import annotations

import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = d.get("action")
        if tag == "input" and d.get("name"):
            self.inputs[d["name"]] = d.get("value") or ""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def rewrite_auth(url: str) -> str:
    u = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(
        ("http", "127.0.0.1:8080", u.path, u.params, u.query, u.fragment)
    )


def main() -> None:
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj))
    follow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    try:
        op.open("http://127.0.0.1:3100/api/auth/oidc/start", timeout=20)
        raise SystemExit("expected redirect from /api/auth/oidc/start")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        print("start", e.code, (loc or "")[:180])
        if not loc or "code_challenge" not in loc:
            raise SystemExit("bad start redirect")

    print("fe_cookies", [c.name for c in cj])

    auth_url = rewrite_auth(loc)
    req = urllib.request.Request(auth_url, headers={"Host": "auth.belakb.by"})
    html = follow.open(req, timeout=20).read().decode("utf-8", "replace")
    parser = FormParser()
    parser.feed(html)
    if not parser.action:
        print("html_snip", html[:500].replace("\n", " "))
        raise SystemExit("no login form")

    action = urllib.parse.urljoin(auth_url, parser.action)
    if "auth.belakb.by" in action:
        action = rewrite_auth(action)

    data = dict(parser.inputs)
    data["username"] = os.environ.get("OIDC_SMOKE_USER", "dima")
    data["password"] = os.environ.get("OIDC_SMOKE_PASSWORD", "")
    if not data["password"]:
        raise SystemExit("set OIDC_SMOKE_PASSWORD")
    print("login_action", action[:140])
    body = urllib.parse.urlencode(data).encode()
    cur: urllib.request.Request = urllib.request.Request(
        action,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "auth.belakb.by",
        },
    )

    callback_url: str | None = None
    for _ in range(10):
        try:
            r = op.open(cur, timeout=30)
            content = r.read().decode("utf-8", "replace")
            print("login_200", str(r.geturl())[:160], "len", len(content))
            print(content[:400])
            break
        except urllib.error.HTTPError as e:
            loc2 = e.headers.get("Location")
            print("redir", e.code, (loc2 or "")[:200])
            if not loc2:
                print(e.read()[:300])
                break
            if "/api/auth/oidc/callback" in loc2:
                callback_url = loc2
                break
            next_url = rewrite_auth(loc2) if "auth.belakb.by" in loc2 else loc2
            hdrs = {"Host": "auth.belakb.by"} if "127.0.0.1:8080" in next_url else {}
            cur = urllib.request.Request(next_url, headers=hdrs)

    print("callback", (callback_url or "")[:220])
    if not callback_url:
        raise SystemExit(3)

    u = urllib.parse.urlparse(callback_url)
    local_cb = f"http://127.0.0.1:3100{u.path}?{u.query}"
    print("local_cb", local_cb[:200])
    try:
        op.open(local_cb, timeout=30)
    except urllib.error.HTTPError as e:
        print("cb", e.code, "loc", (e.headers.get("Location") or "")[:120])
        print(
            "set_cookie_names",
            [s.split("=", 1)[0] for s in (e.headers.get_all("Set-Cookie") or [])],
        )

    token = next((c.value for c in cj if c.name == "aios_access_token"), None)
    role = next((c.value for c in cj if c.name == "aios_role"), None)
    user = next((c.value for c in cj if c.name == "aios_user"), None)
    print("token", bool(token), "role", role, "user", user)
    if not token:
        raise SystemExit(4)

    req = urllib.request.Request(
        "http://127.0.0.1:3100/api/sales/board",
        headers={
            "Cookie": f"aios_access_token={token}; aios_role={role or 'director'}",
        },
    )
    board = json.loads(follow.open(req, timeout=30).read())
    print(
        "board_stages",
        len(board.get("stages", [])) if isinstance(board, dict) else board,
    )

    try:
        follow.open(
            urllib.request.Request(
                "http://127.0.0.1:3100/api/auth/logout",
                method="POST",
                data=b"",
            ),
            timeout=15,
        )
        print("logout_ok")
    except Exception as ex:  # noqa: BLE001
        print("logout", ex)


if __name__ == "__main__":
    main()
