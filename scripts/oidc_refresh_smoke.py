#!/usr/bin/env python3
"""Smoke: obtain OIDC cookies, force near-expiry access, POST /api/auth/oidc/refresh."""

from __future__ import annotations

import http.cookiejar
import json
import os
import time
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


def peek_exp(token: str) -> int | None:
    import base64

    part = token.split(".")[1]
    pad = "=" * ((4 - len(part) % 4) % 4)
    payload = json.loads(base64.urlsafe_b64decode(part + pad))
    exp = payload.get("exp")
    return int(exp) if isinstance(exp, int) else None


def main() -> None:
    password = os.environ.get("OIDC_SMOKE_PASSWORD", "")
    if not password:
        raise SystemExit("set OIDC_SMOKE_PASSWORD")
    user = os.environ.get("OIDC_SMOKE_USER", "dima")

    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj))
    follow = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    try:
        op.open("http://127.0.0.1:3100/api/auth/oidc/start", timeout=20)
        raise SystemExit("expected redirect")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        assert loc and "code_challenge" in loc

    auth_url = rewrite_auth(loc)
    html = follow.open(
        urllib.request.Request(auth_url, headers={"Host": "auth.belakb.by"}),
        timeout=20,
    ).read().decode("utf-8", "replace")
    parser = FormParser()
    parser.feed(html)
    action = urllib.parse.urljoin(auth_url, parser.action or "")
    if "auth.belakb.by" in action:
        action = rewrite_auth(action)
    data = dict(parser.inputs)
    data["username"] = user
    data["password"] = password
    cur = urllib.request.Request(
        action,
        data=urllib.parse.urlencode(data).encode(),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "auth.belakb.by",
        },
    )
    callback_url = None
    for _ in range(10):
        try:
            op.open(cur, timeout=30)
            break
        except urllib.error.HTTPError as e:
            loc2 = e.headers.get("Location")
            if loc2 and "/api/auth/oidc/callback" in loc2:
                callback_url = loc2
                break
            next_url = rewrite_auth(loc2) if loc2 and "auth.belakb.by" in loc2 else loc2
            if not next_url:
                break
            hdrs = {"Host": "auth.belakb.by"} if "127.0.0.1:8080" in next_url else {}
            cur = urllib.request.Request(next_url, headers=hdrs)

    assert callback_url
    u = urllib.parse.urlparse(callback_url)
    local_cb = f"http://127.0.0.1:3100{u.path}?{u.query}"
    try:
        op.open(local_cb, timeout=30)
    except urllib.error.HTTPError as e:
        print("cb", e.code, e.headers.get("Location"))

    access = next(c.value for c in cj if c.name == "aios_access_token")
    refresh = next(c.value for c in cj if c.name == "aios_refresh_token")
    exp_before = peek_exp(access)
    print("exp_before", exp_before, "now", int(time.time()))

    cookie_hdr = f"aios_refresh_token={refresh}; aios_role=director"
    req = urllib.request.Request(
        "http://127.0.0.1:3100/api/auth/oidc/refresh",
        method="POST",
        data=b"",
        headers={"Cookie": cookie_hdr},
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        body = json.loads(r.read())
        print("refresh_status", r.status, body)
        set_cookies = r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        print("refresh_err", e.code, e.read()[:300])
        raise SystemExit(2)

    new_access = None
    for sc in set_cookies:
        if sc.startswith("aios_access_token="):
            new_access = sc.split(";", 1)[0].split("=", 1)[1]
            break
    print("set_cookie_names", [s.split("=", 1)[0] for s in set_cookies])
    print("new_access", bool(new_access), "exp", peek_exp(new_access) if new_access else None)
    if not new_access:
        raise SystemExit(3)

    board = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "http://127.0.0.1:3100/api/sales/board",
                headers={
                    "Cookie": f"aios_access_token={new_access}; aios_role=director",
                },
            ),
            timeout=30,
        ).read()
    )
    print("board_stages", len(board.get("stages", [])) if isinstance(board, dict) else board)


if __name__ == "__main__":
    main()
