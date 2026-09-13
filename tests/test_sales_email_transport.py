import os
import tempfile
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from modules.sales.mail_transport import (
    address,
    configured_sender,
    recipients,
    sales_smtp_config,
    submit,
)


def settings(port=2525):
    return SimpleNamespace(
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_tls=False,
        smtp_user="",
        smtp_password="",
        smtp_from="crm@example.test",
    )


@contextmanager
def receiver(*, data_code=250, rcpt_code=250, drop_after_data=False):
    messages = []

    class Handler(StreamRequestHandler):
        def reply(self, line):
            self.wfile.write(line + b"\r\n")
            self.wfile.flush()

        def handle(self):
            self.reply(b"220 localhost synthetic receiver")
            while line := self.rfile.readline():
                cmd = line.split(b" ", 1)[0].strip().upper()
                if cmd == b"EHLO":
                    self.reply(b"250-localhost")
                    self.reply(b"250 SIZE 20971520")
                elif cmd == b"DATA":
                    self.reply(b"354 Send data")
                    content = bytearray()
                    while (line := self.rfile.readline()) not in (b".\r\n", b""):
                        content.extend(line[1:] if line.startswith(b"..") else line)
                    if data_code == 250:
                        messages.append(bytes(content))
                    if drop_after_data:
                        return
                    self.reply(f"{data_code} synthetic result".encode())
                elif cmd == b"RCPT":
                    self.reply(f"{rcpt_code} synthetic recipient".encode())
                elif cmd == b"QUIT":
                    self.reply(b"221 bye")
                    return
                else:
                    self.reply(b"250 ok")

    server = ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield settings(server.server_address[1]), messages
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "value",
    [
        "a@example.test\r\nBcc: victim@example.test",
        "a@b",
        "Name <a@b.test>",
        "x..y@example.test",
        ".x@example.test",
        "a@-bad.test",
        "a@b..test",
        "a@b.test\x00",
    ],
)
def test_address_rejects_invalid_and_header_injection(value):
    with pytest.raises(ValueError):
        address(value)


def test_recipient_validation_and_deduplication():
    assert recipients([" a@example.test "], ["a@example.test", "b@example.test"]) == (
        ["a@example.test"],
        ["b@example.test"],
    )
    with pytest.raises(ValueError):
        recipients([], ["a@example.test"])
    with pytest.raises(ValueError):
        recipients([f"r{i}@example.test" for i in range(11)], [])


@pytest.mark.parametrize(
    "code, expected", [(250, "accepted"), (451, "retry_wait"), (550, "failed")]
)
def test_real_local_smtp_result(code, expected):
    with receiver(data_code=code) as (config, messages):
        result = submit(
            config,
            config.smtp_from,
            ["control@example.test"],
            b"Subject: test\r\n\r\nSynthetic\r\n",
        )
    assert result.status == expected
    assert result.code == code
    assert len(messages) == (1 if code == 250 else 0)


def test_received_but_final_response_lost_is_uncertain():
    with receiver(drop_after_data=True) as (config, messages):
        result = submit(
            config,
            config.smtp_from,
            ["control@example.test"],
            b"Subject: test\r\n\r\nSynthetic\r\n",
        )
    assert result.status == "uncertain"
    assert len(messages) == 1  # the exact reason a blind retry would duplicate it


def test_permanent_recipient_rejection_sends_no_body():
    with receiver(rcpt_code=550) as (config, messages):
        result = submit(
            config, config.smtp_from, ["bad@example.test"], b"Subject: test\r\n\r\nSynthetic\r\n"
        )
    assert result.status == "failed"
    assert result.reason == "recipient_rejected"
    assert messages == []


def test_auth_refusal_and_secret_redaction(monkeypatch):
    import smtplib

    class SMTP:
        esmtp_features = {}

        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            return 250, b"ok"

        def login(self, *args):
            raise smtplib.SMTPAuthenticationError(535, b"secret=password-value")

        def close(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    config = settings()
    config.smtp_user, config.smtp_password = "test", "password-value"
    result = submit(config, config.smtp_from, ["a@example.test"], b"test")
    assert result.status == "failed" and result.reason == "authentication_rejected"
    assert "password" not in repr(result)


def test_connection_timeout_is_retryable(monkeypatch):
    import smtplib

    def timeout(*args, **kwargs):
        raise TimeoutError("private server detail")

    monkeypatch.setattr(smtplib, "SMTP", timeout)
    config = settings()
    assert submit(config, config.smtp_from, ["a@example.test"], b"test").status == "retry_wait"


def test_unencrypted_remote_smtp_is_rejected_before_network():
    config = settings()
    config.smtp_host = "smtp.example.test"
    assert (
        submit(config, config.smtp_from, ["a@example.test"], b"test").reason
        == "configuration_error"
    )


def test_sales_dedicated_smtp_is_isolated_from_base_settings(monkeypatch):
    fd, secret = tempfile.mkstemp(prefix="sales-smtp-")
    try:
        os.write(fd, b"sales-password\n")
        os.close(fd)
        values = {
            "AIOS_SALES_SMTP_HOST": "sales.example.test",
            "AIOS_SALES_SMTP_PORT": "587",
            "AIOS_SALES_SMTP_USER": "sales-user",
            "AIOS_SALES_SMTP_FROM": "sales@example.test",
            "AIOS_SALES_SMTP_TLS": "true",
            "AIOS_SALES_SMTP_PASSWORD_FILE": secret,
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        config = settings()
        resolved = sales_smtp_config(config)
        assert resolved.host == "sales.example.test"
        assert resolved.password == "sales-password"
        assert configured_sender(config) == "sales@example.test"
        assert config.smtp_host == "127.0.0.1" and config.smtp_from == "crm@example.test"
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        os.unlink(secret)


def test_sales_dedicated_smtp_partial_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("AIOS_SALES_SMTP_HOST", "sales.example.test")
    with pytest.raises(ValueError, match="не полностью"):
        configured_sender(settings())


@pytest.mark.parametrize("stage, expected", [("starttls", "failed"), ("data", "uncertain")])
def test_tls_failure_after_data_is_ambiguous(monkeypatch, stage, expected):
    import smtplib
    import ssl

    def tls_error(*args, **kwargs):
        raise ssl.SSLEOFError("Synthetic TLS connection loss")

    monkeypatch.setattr(smtplib.SMTP, stage, tls_error)
    with receiver() as (config, messages):
        config.smtp_tls = stage == "starttls"
        result = submit(
            config, config.smtp_from, ["a@example.test"], b"Subject: test\r\n\r\nTest\r\n"
        )
    assert result.status == expected


def parse_message(data):
    return BytesParser(policy=policy.default).parsebytes(data)
