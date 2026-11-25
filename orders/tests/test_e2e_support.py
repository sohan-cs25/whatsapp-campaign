"""Support code for the local end-to-end setup (see e2e/README.md)."""

import json
import tempfile
import threading
import urllib.request
from decimal import Decimal as D
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from orders.models import Order, ParsedChatFile, Product
from orders.tests.helpers import add_line, make_parsed_file, make_products, make_user

REPO = Path(settings.BASE_DIR)


class SendAllowlistTests(TestCase):
    def setUp(self):
        user = make_user()
        mango, _ = make_products()
        self.order = Order.objects.create(user=user, parsed_file=make_parsed_file(user), number="919800000001",
                                          order_items="", amount="", review_status="approved")
        add_line(self.order, mango, D("1"), "kg")
        self.order.refresh_totals()
        patcher = patch("campaigns.whatsapp_360_client.WhatsApp360Client")
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client_cls.return_value.send_message.return_value = {
            "success": True, "message_id": "wamid.x", "status_code": 200}

    def send(self):
        from orders.whatsapp_service import OrderWhatsAppService
        OrderWhatsAppService().send_order_message(self.order)
        self.order.refresh_from_db()

    @override_settings(ORDERS_SEND_ALLOWLIST=["919811111111"])
    def test_number_outside_allowlist_is_not_sent(self):
        self.send()
        self.client_cls.return_value.send_message.assert_not_called()
        assert self.order.status == "failed"
        assert "ORDERS_SEND_ALLOWLIST" in self.order.whatsapp_response_json["error"]

    @override_settings(ORDERS_SEND_ALLOWLIST=["919800000001"])
    def test_number_in_allowlist_is_sent(self):
        self.send()
        assert self.order.status == "sent"


class SeedCommandTests(TestCase):
    def seed(self, *args):
        out = StringIO()
        call_command("seed_e2e", *args, stdout=out)
        return out.getvalue()

    def test_refuses_outside_e2e_mode(self):
        with self.assertRaises(CommandError):
            self.seed()

    @override_settings(E2E_MODE=True)
    def test_seeds_user_and_products_idempotently(self):
        self.seed()
        self.seed()
        user = User.objects.get(username="e2e")
        assert user.check_password("e2e-pass-123")
        assert user.has_perm("orders.change_product") and user.has_perm("orders.add_product")
        assert Product.objects.filter(is_active=True).count() == 4
        assert Product.objects.get(key="kesar_mango").price == D("120")

    @override_settings(E2E_MODE=True)
    def test_with_orders_builds_a_review_ready_file(self):
        self.seed("--with-orders")
        pf = ParsedChatFile.objects.get(user__username="e2e")
        orders = {o.customer_name: o for o in pf.orders.all()}
        assert len(orders) == 5
        clean = [o for o in orders.values() if not o.needs_review]
        assert clean and all(not o.blocking_issues() for o in clean)
        issues = {i for o in orders.values() for i in o.blocking_issues()}
        assert {"no_phone", "unpriced_line"} <= issues
        assert any("had_cancellation" in o.review_flags for o in orders.values())

    @override_settings(E2E_MODE=True)
    def test_with_orders_twice_replaces_draft_file(self):
        self.seed("--with-orders")
        self.seed("--with-orders")
        assert ParsedChatFile.objects.filter(user__username="e2e").count() == 1


class SampleChatTests(TestCase):
    def test_sample_chat_parses(self):
        from orders.tools.chat_parser import parse_chat_content
        msgs = parse_chat_content((REPO / "e2e" / "sample_chat.txt").read_text(encoding="utf-8"))
        assert len(msgs) >= 20
        assert "Aj" in {m["Phone/Name"] for m in msgs}


class FakeWhatsAppTests(TestCase):
    def test_records_payload_and_returns_message_id(self):
        from e2e.fake_whatsapp import make_server
        with tempfile.TemporaryDirectory() as outbox:
            server = make_server("127.0.0.1", 0, Path(outbox))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/messages",
                                         data=json.dumps({"to": "919800000001"}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
            assert resp.status == 200 and body["messages"][0]["id"].startswith("wamid.e2e")
            saved = list(Path(outbox).glob("*.json"))
            assert len(saved) == 1 and json.loads(saved[0].read_text())["to"] == "919800000001"
