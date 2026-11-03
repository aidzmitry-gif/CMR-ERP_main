import base64
import hashlib
import io
import json
import os
import shutil
import threading
import unittest
import urllib.error
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ops.sales_mail import cli as sales_cli
from ops.sales_mail.config import (
    ENDPOINT,
    IMAP_HOST,
    IMAP_PORT,
    MAILBOX,
    Config,
    ConfigError,
    load_config,
)
from ops.sales_mail.imap_stage import ImapError, UIDValidityChanged, initialize, poll_once
from ops.sales_mail.lock import InstanceLock, LockBusy
from ops.sales_mail.queue import Queue, QueueError, QueueHalted, QueueNamespaceMismatch
from ops.sales_mail.relay import (
    MAX_RESPONSE_BYTES,
    HTTPResponse,
    RemoteEndpointError,
    ResponseTooLarge,
    TransientRelayError,
    _post,
    receipt_id,
    relay_once,
)


class FakeIMAP:
    def __init__(self, *, uidvalidity=7, uidnext=1, messages=None, oversized=None, fail_body=None):
        self.uidvalidity = uidvalidity
        self.uidnext = uidnext
        self.messages = dict(messages or {})
        self.oversized = dict(oversized or {})
        self.fail_body = set(fail_body or ())
        self.calls = []
        self.closed = False

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def response(self, name):
        self.calls.append(("response", name))
        values = {"UIDVALIDITY": self.uidvalidity, "UIDNEXT": self.uidnext}
        return name, [str(values[name]).encode("ascii")]

    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "search":
            uids = sorted(self.messages)
            return "OK", [b" ".join(str(uid).encode("ascii") for uid in uids)]
        uid = int(args[0])
        if command != "fetch":
            raise AssertionError(command)
        if args[1] == "(RFC822.SIZE)":
            size = self.oversized.get(uid, len(self.messages[uid]))
            return "OK", [f"{uid} (RFC822.SIZE {size})".encode("ascii")]
        if args[1] == "(BODY.PEEK[])" and uid in self.fail_body:
            return "NO", []
        if args[1] == "(BODY.PEEK[])":
            raw = self.messages[uid]
            return "OK", [(f"{uid} (BODY.PEEK[] {{{len(raw)}}})".encode("ascii"), raw), b")"]
        raise AssertionError(args[1])

    def close(self):
        self.closed = True

    def logout(self):
        return "BYE", []


def make_config(endpoint=ENDPOINT):
    return Config(
        mailbox=MAILBOX,
        imap_host=IMAP_HOST,
        imap_port=IMAP_PORT,
        username=MAILBOX,
        password="fake-password",
        endpoint=endpoint,
        inbound_token="fake-token",
    )


class SalesMailIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_root = Path.cwd() / ".tmp_sales_mail_tests_v2"
        cls.test_root.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_root, ignore_errors=True)

    def setUp(self):
        self.tempdir = self.test_root / self.id().rsplit(".", 1)[-1]
        if self.tempdir.exists():
            shutil.rmtree(self.tempdir, ignore_errors=True)
        self.tempdir.mkdir()
        self.queue_path = self.tempdir / "queue.sqlite"

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def open_queue(self):
        return Queue(self.queue_path)

    def initialized_queue(self, *, uidvalidity=7, uidnext=1):
        queue = self.open_queue()
        queue.initialize(MAILBOX, uidvalidity, uidnext)
        return queue

    def test_initialize_sets_uidnext_boundary_without_history(self):
        fake = FakeIMAP(uidvalidity=12, uidnext=10, messages={uid: b"old" for uid in range(1, 10)})
        with self.open_queue() as queue:
            result = initialize(queue, make_config(), lambda _: fake)
            self.assertEqual({"initialized": True, "history_imported": False}, result)
            self.assertEqual(9, queue.last_uid)
            self.assertEqual([], [call for call in fake.calls if call[0] in ("search", "fetch")])

    def test_init_cannot_reset_existing_queue_or_change_namespace(self):
        fake = FakeIMAP(uidvalidity=12, uidnext=10)
        with self.open_queue() as queue:
            initialize(queue, make_config(), lambda _: fake)
            with self.assertRaises(QueueError):
                initialize(queue, make_config(), lambda _: fake)
        with self.open_queue() as queue:
            queue._set("mailbox", "other@example.invalid")
            with self.assertRaises(QueueNamespaceMismatch):
                initialize(queue, make_config(), lambda _: fake)

    def test_initialize_metadata_rolls_back_as_one_transaction(self):
        with self.open_queue() as queue:
            original_set = queue._set

            def fail_after_uidvalidity(key, value):
                original_set(key, value)
                if key == "last_uid":
                    raise RuntimeError("injected_init_fault")

            with patch.object(queue, "_set", side_effect=fail_after_uidvalidity):
                with self.assertRaisesRegex(RuntimeError, "injected_init_fault"):
                    queue.initialize(MAILBOX, 7, 10)
            self.assertFalse(queue.initialized)
            self.assertEqual(0, queue.last_uid)
        with self.open_queue() as reopened:
            self.assertFalse(reopened.initialized)
            self.assertEqual(0, reopened.last_uid)

    def test_stage_and_cursor_roll_back_together_as_one_transaction(self):
        raw = b"From: a\r\n\r\nbody"
        with self.initialized_queue() as queue:
            with patch.object(queue, "_advance", side_effect=RuntimeError("injected_stage_fault")):
                with self.assertRaisesRegex(RuntimeError, "injected_stage_fault"):
                    queue.stage_raw(1, raw)
            self.assertEqual(0, queue.last_uid)
            self.assertIsNone(
                queue.db.execute(
                    "SELECT 1 FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                    (MAILBOX, 7, 1),
                ).fetchone()
            )
        with self.open_queue() as reopened:
            self.assertEqual(0, reopened.last_uid)
            self.assertEqual({}, reopened.status()["counts"])

    def test_pending_yields_one_raw_blob_after_bounded_identity_query(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\none")
            queue.stage_raw(2, b"From: b\r\n\r\ntwo")
            statements = []
            queue.db.set_trace_callback(statements.append)
            pending = queue.pending()
            self.assertEqual([], statements)
            first = next(pending)
            self.assertIn("SELECT mailbox,uidvalidity,uid,raw_sha256", statements[0])
            self.assertNotIn("SELECT raw FROM messages", statements[0])
            self.assertEqual(b"From: a\r\n\r\none", first.raw)
            raw_queries = [statement for statement in statements if "SELECT raw FROM messages" in statement]
            self.assertEqual(1, len(raw_queries))
            second = next(pending)
            self.assertEqual(b"From: b\r\n\r\ntwo", second.raw)
            raw_queries = [statement for statement in statements if "SELECT raw FROM messages" in statement]
            self.assertEqual(2, len(raw_queries))

    def test_restart_deduplicates_and_preserves_cursor(self):
        first = FakeIMAP(uidvalidity=7, uidnext=3, messages={1: b"From: a\r\n\r\none", 2: b"From: b\r\n\r\ntwo"})
        with self.initialized_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: first)
            self.assertEqual(2, result["pending"])
            self.assertEqual(2, queue.last_uid)
        second = FakeIMAP(uidvalidity=7, uidnext=3, messages=first.messages)
        with self.open_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: second)
            self.assertEqual({"fetched": 0, "pending": 0, "review": 0, "oversize": 0}, result)
            self.assertEqual(0, len([call for call in second.calls if call[0] == "fetch"]))
            self.assertEqual(2, queue.status()["counts"]["pending"])

    def test_partial_fetch_failure_keeps_failed_uid_for_restart(self):
        failing = FakeIMAP(
            uidvalidity=7,
            uidnext=3,
            messages={1: b"From: a\r\n\r\none", 2: b"From: b\r\n\r\ntwo"},
            fail_body={2},
        )
        with self.initialized_queue() as queue:
            with self.assertRaisesRegex(RuntimeError, "body_fetch_failed"):
                poll_once(queue, make_config(), lambda _: failing)
            self.assertEqual(1, queue.last_uid)
        recovered = FakeIMAP(uidvalidity=7, uidnext=3, messages=failing.messages)
        with self.open_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: recovered)
            self.assertEqual(1, result["pending"])
            self.assertEqual(2, queue.last_uid)

    def test_oversize_is_reviewable_and_body_is_not_fetched(self):
        fake = FakeIMAP(
            uidvalidity=7,
            uidnext=2,
            messages={1: b"placeholder"},
            oversized={1: 32 * 1024 * 1024 + 1},
        )
        with self.initialized_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: fake)
            self.assertEqual(1, result["oversize"])
            self.assertEqual(1, queue.last_uid)
            row = queue.db.execute(
                "SELECT raw,state,reason FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (MAILBOX, 7, 1),
            ).fetchone()
            self.assertIsNone(row["raw"])
            self.assertEqual("review", row["state"])
            self.assertEqual("oversized_original_in_mailbox", row["reason"])
        self.assertNotIn(("fetch", "1", "(BODY.PEEK[])"), fake.calls)

    def test_malformed_message_is_staged_for_review(self):
        malformed = b"Content-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\nbody"
        fake = FakeIMAP(uidvalidity=7, uidnext=2, messages={1: malformed})
        with self.initialized_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: fake)
            self.assertEqual(1, result["review"])
            row = queue.db.execute(
                "SELECT state,reason FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (MAILBOX, 7, 1),
            ).fetchone()
            self.assertEqual(("review", "message_parse_defects"), tuple(row))

    def test_uidvalidity_change_durably_halts_without_advancing(self):
        fake = FakeIMAP(uidvalidity=8, uidnext=2, messages={1: b"new"})
        with self.initialized_queue(uidvalidity=7) as queue:
            with self.assertRaises(UIDValidityChanged):
                poll_once(queue, make_config(), lambda _: fake)
            self.assertTrue(queue.collection_halted)
            self.assertEqual(0, queue.last_uid)
            self.assertEqual("8", queue._get("halt_new_uidvalidity"))
            self.assertEqual("7", queue._get("halt_observed_uidvalidity"))

    def test_malformed_search_does_not_advance_cursor(self):
        class MalformedSearch(FakeIMAP):
            def __init__(self, search_data):
                super().__init__(uidvalidity=7, uidnext=2)
                self.search_data = search_data

            def uid(self, command, *args):
                if command == "search":
                    self.calls.append((command, *args))
                    return "OK", self.search_data
                return super().uid(command, *args)

        for index, search_data in enumerate((None, [b"1 invalid-token"])):
            self.queue_path = self.tempdir / f"queue-{index}.sqlite"
            with self.subTest(search_data=search_data), self.initialized_queue() as queue:
                with self.assertRaisesRegex(RuntimeError, "search_"):
                    poll_once(queue, make_config(), lambda _, data=search_data: MalformedSearch(data))
                self.assertEqual(0, queue.last_uid)
                self.assertEqual({}, queue.status()["counts"])

    def test_valid_empty_search_can_advance_to_observed_upper_bound(self):
        fake = FakeIMAP(uidvalidity=7, uidnext=2, messages={})
        with self.initialized_queue() as queue:
            result = poll_once(queue, make_config(), lambda _: fake)
            self.assertEqual({"fetched": 0, "pending": 0, "review": 0, "oversize": 0}, result)
            self.assertEqual(1, queue.last_uid)

    def test_wrong_receipt_response_is_review_and_never_delivered(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            result = relay_once(
                queue,
                make_config(),
                post=lambda _config, _payload: HTTPResponse(
                    200,
                    json.dumps({"receipt_id": "0" * 64, "raw_sha256": "f" * 64}).encode(),
                ),
            )
            self.assertEqual(1, result["review"])
            self.assertEqual({"review": 1}, queue.status()["counts"])

    def test_uidvalidity_halt_blocks_relay_until_recovery(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            queue.halt_uidvalidity(7, 8)
            with self.assertRaises(QueueHalted):
                relay_once(
                    queue,
                    make_config(),
                    post=lambda _config, _payload: self.fail("halted queue must not post"),
                )
            self.assertEqual(1, queue.status()["counts"]["pending"])

    def test_remote_redirect_halts_relay_without_following_it(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            result = relay_once(
                queue,
                make_config(),
                post=lambda _config, _payload: (_ for _ in ()).throw(
                    RemoteEndpointError("remote_redirect_rejected")
                ),
            )
            self.assertEqual(1, result["halted"])
            self.assertTrue(queue.relay_halted)
            self.assertEqual(1, queue.status()["counts"]["pending"])

    def test_network_retry_reuses_exact_payload_and_then_delivers(self):
        payloads = []
        attempts = {"count": 0}
        raw = b"From: a\r\n\r\nbody"

        def post(_config, payload):
            attempts["count"] += 1
            payloads.append(payload)
            if attempts["count"] < 3:
                raise TransientRelayError("relay_network_error")
            data = json.loads(payload)
            return HTTPResponse(
                200,
                json.dumps({"receipt_id": receipt_id(MAILBOX, 7, 1), "raw_sha256": data["raw_sha256"]}).encode(),
            )

        with self.initialized_queue() as queue:
            queue.stage_raw(1, raw)
            result = relay_once(queue, make_config(), post=post)
            self.assertEqual({"delivered": 1, "pending": 0, "review": 0, "halted": 0}, result)
            self.assertEqual(3, attempts["count"])
            self.assertEqual(payloads[0], payloads[1])
            self.assertEqual(payloads[1], payloads[2])
            self.assertEqual(1, queue.status()["counts"]["delivered"])

    def test_429_is_bounded_and_remains_pending_for_next_poll(self):
        calls = {"count": 0}

        def post(_config, _payload):
            calls["count"] += 1
            return HTTPResponse(429, b"ignored")

        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            result = relay_once(queue, make_config(), post=post)
            self.assertEqual({"delivered": 0, "pending": 1, "review": 0, "halted": 0}, result)
            self.assertEqual(3, calls["count"])
            self.assertEqual(1, queue.status()["counts"]["pending"])

    def test_409_is_review_and_does_not_overwrite_raw(self):
        raw = b"From: a\r\n\r\nbody"
        with self.initialized_queue() as queue:
            queue.stage_raw(1, raw)
            result = relay_once(
                queue,
                make_config(),
                post=lambda _config, _payload: HTTPResponse(409, b"conflict"),
            )
            self.assertEqual(1, result["review"])
            row = queue.db.execute(
                "SELECT raw,state,reason FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (MAILBOX, 7, 1),
            ).fetchone()
            self.assertEqual(raw, bytes(row["raw"]))
            self.assertEqual(("review", "receipt_conflict"), (row["state"], row["reason"]))

    def test_loopback_fake_relay_receives_token_and_contract_payload(self):
        received = {}
        expected_raw = b"From: a\r\n\r\nbody"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received["path"] = self.path
                received["token"] = self.headers.get("X-Sales-Mail-Token")
                length = int(self.headers["Content-Length"])
                received["payload"] = json.loads(self.rfile.read(length))
                response = {
                    "receipt_id": receipt_id(MAILBOX, 7, 1),
                    "raw_sha256": hashlib.sha256(expected_raw).hexdigest(),
                }
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/integrations/sales-mail/v1"
            config = make_config(endpoint)
            with patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "http_proxy": "http://127.0.0.1:1",
                    "https_proxy": "http://127.0.0.1:1",
                    "NO_PROXY": "",
                    "no_proxy": "",
                },
            ):
                with self.initialized_queue() as queue:
                    queue.stage_raw(1, expected_raw)
                    result = relay_once(queue, config)
                    self.assertEqual(1, result["delivered"])
            self.assertEqual("/integrations/sales-mail/v1", received["path"])
            self.assertEqual("fake-token", received["token"])
            self.assertEqual(MAILBOX, received["payload"]["mailbox"])
            self.assertEqual(7, received["payload"]["uidvalidity"])
            self.assertEqual(1, received["payload"]["uid"])
            self.assertEqual(expected_raw, base64.b64decode(received["payload"]["raw_base64"]))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_401_halts_relay_and_leaves_pending(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            result = relay_once(
                queue,
                make_config(),
                post=lambda _config, _payload: HTTPResponse(401, b"ignored"),
            )
            self.assertEqual(1, result["halted"])
            self.assertTrue(queue.relay_halted)
            self.assertEqual(1, queue.status()["counts"]["pending"])

    def test_cli_run_relays_existing_pending_after_ordinary_poll_error(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
        output = io.StringIO()
        with (
            patch.object(sales_cli, "load_config", return_value=make_config()),
            patch.object(sales_cli, "poll_once", side_effect=ImapError("fetch_failed")) as poll,
            patch.object(sales_cli, "relay_once", return_value={"delivered": 1}) as relay,
            redirect_stdout(output),
        ):
            result = sales_cli.main(
                ["run", "--config", "unused.json", "--queue", str(self.queue_path)]
            )
        self.assertEqual(1, result)
        poll.assert_called_once()
        relay.assert_called_once()
        rendered = output.getvalue()
        self.assertIn('"operation_failed":true', rendered)
        self.assertIn('"relay":{"delivered":1}', rendered)

    def test_http_response_and_http_error_bodies_are_bounded(self):
        class OversizeResponse:
            status = 200
            headers = {}

            def __init__(self):
                self.read_size = None

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size):
                self.read_size = size
                return b"x" * size

        response = OversizeResponse()

        class ResponseOpener:
            def open(self, *_args, **_kwargs):
                return response

        with patch("urllib.request.build_opener", return_value=ResponseOpener()):
            with self.assertRaises(ResponseTooLarge):
                _post(make_config(), b"{}")
        self.assertEqual(MAX_RESPONSE_BYTES + 1, response.read_size)

        class OversizeErrorBody:
            def __init__(self):
                self.read_size = None

            def read(self, size=-1):
                self.read_size = size
                return b"x" * (MAX_RESPONSE_BYTES + 1)

            def close(self):
                return None

        error_body = OversizeErrorBody()
        error = urllib.error.HTTPError(
            ENDPOINT,
            500,
            "server error",
            hdrs={},
            fp=error_body,
        )

        class ErrorOpener:
            def open(self, *_args, **_kwargs):
                raise error

        with patch("urllib.request.build_opener", return_value=ErrorOpener()):
            with self.assertRaises(ResponseTooLarge):
                _post(make_config(), b"{}")
        self.assertEqual(MAX_RESPONSE_BYTES + 1, error_body.read_size)

    def test_oversize_relay_response_becomes_durable_review(self):
        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")

            def oversize_post(_config, _payload):
                raise ResponseTooLarge("relay_response_too_large")

            result = relay_once(queue, make_config(), post=oversize_post)
            self.assertEqual(1, result["review"])
            row = queue.db.execute(
                "SELECT state,reason FROM messages WHERE mailbox=? AND uidvalidity=? AND uid=?",
                (MAILBOX, 7, 1),
            ).fetchone()
            self.assertEqual(("review", "relay_response_too_large"), tuple(row))

    def test_oversize_response_after_transient_retry_is_review_not_pending(self):
        calls = {"count": 0}

        def post(_config, _payload):
            calls["count"] += 1
            if calls["count"] == 1:
                return HTTPResponse(500, b"retry")
            raise ResponseTooLarge("relay_response_too_large")

        with self.initialized_queue() as queue:
            queue.stage_raw(1, b"From: a\r\n\r\nbody")
            result = relay_once(queue, make_config(), post=post)
            self.assertEqual(1, result["review"])
            self.assertEqual(0, result["pending"])
            self.assertEqual(2, calls["count"])

    @unittest.skipUnless(os.name != "nt", "POSIX mode bits are not Windows ACL enforcement")
    def test_private_queue_and_config_permissions_are_required(self):
        with self.open_queue() as queue:
            queue.close()
        self.queue_path.chmod(0o644)
        with self.assertRaisesRegex(QueueError, "private_permissions"):
            Queue(self.queue_path)

        config_path = self.tempdir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "mailbox": MAILBOX,
                    "imap_host": IMAP_HOST,
                    "imap_port": IMAP_PORT,
                    "username": MAILBOX,
                    "password": "placeholder",
                    "endpoint": ENDPOINT,
                    "inbound_token": "placeholder",
                }
            ),
            encoding="utf-8",
        )
        config_path.chmod(0o644)
        with self.assertRaisesRegex(ConfigError, "private_permissions"):
            load_config(config_path)

    def test_config_fails_closed_for_remote_hosts_and_account_changes(self):
        path = self.tempdir / "config.json"
        path.write_text(
            json.dumps(
                {
                    "mailbox": MAILBOX,
                    "imap_host": IMAP_HOST,
                    "imap_port": IMAP_PORT,
                    "username": MAILBOX,
                    "password": "placeholder",
                    "endpoint": "http://remote.example/integrations/sales-mail/v1",
                    "inbound_token": "placeholder",
                }
            ),
            encoding="utf-8",
        )
        if os.name != "nt":
            path.chmod(0o600)
        with self.assertRaisesRegex(ConfigError, "unexpected_endpoint"):
            load_config(path)

    def test_instance_lock_does_not_delete_live_lock(self):
        lock_path = self.tempdir / "worker.lock"
        with InstanceLock(lock_path):
            with self.assertRaises(LockBusy):
                with InstanceLock(lock_path):
                    pass
        self.assertTrue(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
