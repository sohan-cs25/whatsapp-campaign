"""Flat -> phone directory (filled in automatically, learned from review) and the chat
messages kept with each processed file so reviewers can see where an order came from."""

import os
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from orders.models import ChatFile, ChatMessage, CustomerContact, Order, ParsedChatFile, flat_key, normalize_phone
from orders.order_builder import build_orders
from orders.tests.helpers import add_line, make_parsed_file, make_products, make_user
from orders.tests.test_builder import row


class NormalisationTests(SimpleTestCase):
    def test_flat_key(self):
        cases = {"C-234": "C234", "234-c": "C234", "234 C": "C234", "House 182": "182", "182": "182",
                 "B 178": "B178", "159B": "B159", "#261": "261", "182-Jalvayu": "182", "": "", None: "",
                 "Jalvayu": "", "98.A.JVV": "A98"}
        for raw, key in cases.items():
            assert flat_key(raw) == key, (raw, flat_key(raw), key)

    def test_normalize_phone(self):
        assert normalize_phone("98765 43210") == "919876543210"
        assert normalize_phone("+91 98765-43210") == "919876543210"
        assert normalize_phone("919876543210") == "919876543210"
        assert normalize_phone("12345") == "" and normalize_phone(None) == ""


class DirectoryInBuilderTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.pf = make_parsed_file(self.user)
        make_products()

    def test_phone_filled_from_directory_by_flat(self):
        CustomerContact.objects.create(user=self.user, flat="C-710", phone="9198000 00001")
        (o,) = build_orders(self.pf, pd.DataFrame([row(sender="Asha JVV", address="C-710")]))
        assert o.number == "919800000001"
        assert "phone_from_directory" in o.review_flags
        assert o.blocking_issues() == [] and o.needs_review is False

    def test_other_users_directory_not_used(self):
        CustomerContact.objects.create(user=make_user("other"), flat="C-710", phone="919800000001")
        (o,) = build_orders(self.pf, pd.DataFrame([row(sender="Asha JVV", address="C-710")]))
        assert o.number == "" and "no_phone" in o.blocking_issues()

    def test_phone_in_chat_wins_over_directory(self):
        CustomerContact.objects.create(user=self.user, flat="C-710", phone="919800000001")
        (o,) = build_orders(self.pf, pd.DataFrame([row(sender="919811111111", address="C-710")]))
        assert o.number == "919811111111" and "phone_from_directory" not in o.review_flags

    def test_order_remembers_chat_sender(self):
        (o,) = build_orders(self.pf, pd.DataFrame([row(sender="Asha JVV", address="C-710")]))
        assert o.chat_sender == "Asha JVV"


class DirectoryApiTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.pf = make_parsed_file(self.user)
        self.mango, _ = make_products()

    def order(self, address, number="", status="pending", review_status="draft", user=None):
        o = Order.objects.create(user=user or self.user, parsed_file=self.pf, customer_name="Asha", number=number,
                                 address=address, order_items="", amount="", status=status,
                                 review_status=review_status)
        add_line(o, self.mango, D("1"), "kg")
        o.refresh_totals()
        return o

    def test_reviewer_phone_is_remembered_for_the_flat(self):
        o = self.order("C-234")
        r = self.client.patch(f"/api/orders/review/orders/{o.id}/", {"number": "98000 00001"}, format="json")
        assert r.status_code == 200
        c = CustomerContact.objects.get(user=self.user)
        assert (c.flat_key, c.phone, c.name) == ("C234", "919800000001", "Asha")
        self.client.patch(f"/api/orders/review/orders/{o.id}/", {"number": "919800000002"}, format="json")
        assert CustomerContact.objects.get(user=self.user).phone == "919800000002"

    def test_invalid_reviewer_phone_not_remembered(self):
        o = self.order("C-234")
        self.client.patch(f"/api/orders/review/orders/{o.id}/", {"number": "123"}, format="json")
        assert not CustomerContact.objects.exists()

    def test_address_edit_fills_phone_from_directory(self):
        CustomerContact.objects.create(user=self.user, flat="182", phone="919800000003")
        o = self.order("")
        r = self.client.patch(f"/api/orders/review/orders/{o.id}/", {"address": "House 182"}, format="json")
        assert r.data["number"] == "919800000003" and r.data["blocking_issues"] == []

    def test_list_is_per_user(self):
        CustomerContact.objects.create(user=self.user, flat="C-234", phone="919800000001")
        CustomerContact.objects.create(user=make_user("other"), flat="C-234", phone="919800000009")
        r = self.client.get("/api/orders/customers/")
        assert r.status_code == 200 and [c["phone"] for c in r.data] == ["919800000001"]

    def test_create_normalises_and_upserts(self):
        r = self.client.post("/api/orders/customers/", {"flat": "234-c", "phone": "98000 00001"}, format="json")
        assert r.status_code == 201 and r.data["phone"] == "919800000001" and r.data["flat_key"] == "C234"
        r = self.client.post("/api/orders/customers/", {"flat": "C-234", "phone": "9800000002"}, format="json")
        assert r.status_code == 201
        assert CustomerContact.objects.get(user=self.user).phone == "919800000002"

    def test_invalid_phone_or_flat_400(self):
        assert self.client.post("/api/orders/customers/", {"flat": "C-234", "phone": "12"},
                                format="json").status_code == 400
        assert self.client.post("/api/orders/customers/", {"flat": "Jalvayu", "phone": "9800000001"},
                                format="json").status_code == 400

    def test_saving_contact_fills_waiting_orders(self):
        waiting = self.order("C-234")
        other_flat = self.order("C-235")
        sent = self.order("C-234", status="sent", review_status="approved")
        has_phone = self.order("C-234", number="919811111111")
        r = self.client.post("/api/orders/customers/", {"flat": "234C", "phone": "9800000001"}, format="json")
        assert r.data["orders_filled"] == 1
        for o in (waiting, other_flat, sent, has_phone):
            o.refresh_from_db()
        assert waiting.number == "919800000001" and "phone_from_directory" in waiting.review_flags
        assert other_flat.number == "" and sent.number == "" and has_phone.number == "919811111111"

    def test_delete_and_other_users_contact_404(self):
        mine = CustomerContact.objects.create(user=self.user, flat="C-234", phone="919800000001")
        theirs = CustomerContact.objects.create(user=make_user("other"), flat="C-234", phone="919800000009")
        assert self.client.delete(f"/api/orders/customers/{theirs.id}/").status_code == 404
        assert self.client.delete(f"/api/orders/customers/{mine.id}/").status_code == 204
        assert CustomerContact.objects.count() == 1


CHAT = (
    "25/01/2025, 5:15 pm - Aj: Please share your orders\n"
    "25/01/2025, 5:18 pm - Mekhala Jvv: 236 JVV\nTomato 1 kg\n"
    "26/01/2025, 6:49 am - Neelima Jvv: <Media omitted>\n"
    "26/01/2025, 8:43 am - Mekhala Jvv: thanks\n"
)


class ChatMessagesStoredTests(TestCase):
    def test_process_stores_every_message_with_its_id(self):
        from orders.tasks import process_chat_file
        user = make_user()
        rel = "chatfile/test_messages_chat.txt"
        path = os.path.join(settings.ORDERS_MEDIA_ROOT, rel)
        with open(path, "w", encoding="utf-8") as f:
            f.write(CHAT)
        self.addCleanup(os.remove, path)
        chat = ChatFile.objects.create(user=user, filename="test_messages_chat.txt", filepath=rel, filetype="text")
        empty = pd.DataFrame(columns=["message_ids"])
        result = {"catalog": [], "orders": empty, "totals": empty, "labels": {}}
        with patch("orders.ai_service.ox.get_llm"), patch("orders.ai_service.ox.run", return_value=result), \
                patch("orders.tasks.save_enhanced_messages_to_excel", return_value=True), \
                patch("orders.ai_service.django_ai_service.default_sellers", {"Aj"}):
            out = process_chat_file.apply(args=[str(chat.id)]).get()
        assert out["success"], out
        pf = ParsedChatFile.objects.get(chatfile=chat)
        msgs = list(pf.messages.order_by("position"))
        assert [(m.msg_id, m.sender, m.is_seller) for m in msgs] == [
            ("m0", "Aj", True), ("m1", "Mekhala Jvv", False), ("", "Neelima Jvv", False), ("m2", "Mekhala Jvv", False)]
        assert msgs[1].text.startswith("236 JVV") and msgs[2].text == "<Media omitted>"
        # processing again (a retry) replaces the messages instead of duplicating them
        chat.is_processed = False
        chat.save()
        with patch("orders.ai_service.ox.get_llm"), patch("orders.ai_service.ox.run", return_value=result), \
                patch("orders.tasks.save_enhanced_messages_to_excel", return_value=True):
            process_chat_file.apply(args=[str(chat.id)]).get()
        assert pf.messages.count() == 4


class ReviewShowsMessagesTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.pf = make_parsed_file(self.user)
        self.mango, _ = make_products()
        for i, (mid, sender, text, seller) in enumerate([
                ("m0", "Aj", "Kesar 120/kg", True),
                ("m1", "Asha", "1 kg kesar", False),
                ("m2", "Asha", "C-710 please", False),
                ("", "Neelima", "<Media omitted>", False),
                ("m3", "Aj", "Kesar out of stock", True)]):
            ChatMessage.objects.create(parsed_file=self.pf, position=i, msg_id=mid, date="25/01/2025",
                                       time="5:15 PM", sender=sender, text=text, is_seller=seller)
        self.order = Order.objects.create(user=self.user, parsed_file=self.pf, customer_name="Asha",
                                          chat_sender="Asha", number="", address="C-710", order_items="", amount="")
        line = add_line(self.order, self.mango, D("1"), "kg")
        line.message_ids = "m1"
        line.save()

    def test_order_has_its_customers_messages_with_used_marked(self):
        r = self.client.get(f"/api/orders/review/{self.pf.id}/")
        (o,) = r.data["orders"]
        assert [(m["text"], m["used"]) for m in o["messages"]] == [("1 kg kesar", True), ("C-710 please", False)]
        assert o["messages"][0]["time"] == "5:15 PM" and o["messages"][0]["date"] == "25/01/2025"

    def test_seller_and_unordered_messages_listed(self):
        r = self.client.get(f"/api/orders/review/{self.pf.id}/")
        assert [m["text"] for m in r.data["seller_messages"]] == ["Kesar 120/kg", "Kesar out of stock"]
        assert [(m["sender"], m["text"]) for m in r.data["unordered_messages"]] == [("Neelima", "<Media omitted>")]

    def test_renaming_customer_keeps_messages(self):
        self.client.patch(f"/api/orders/review/orders/{self.order.id}/", {"customer_name": "Asha K"}, format="json")
        (o,) = self.client.get(f"/api/orders/review/{self.pf.id}/").data["orders"]
        assert len(o["messages"]) == 2


class ReviewerPhoneNormalisedTests(DirectoryApiTests):
    def test_typed_phone_with_spaces_is_cleaned_on_the_order(self):
        o = self.order("C-234")
        r = self.client.patch(f"/api/orders/review/orders/{o.id}/", {"number": "90000 11236"}, format="json")
        assert r.data["number"] == "919000011236" and r.data["blocking_issues"] == []

    def test_unusable_phone_is_kept_as_typed_and_still_blocks(self):
        o = self.order("C-234")
        r = self.client.patch(f"/api/orders/review/orders/{o.id}/", {"number": "12345"}, format="json")
        assert r.data["number"] == "12345" and "no_phone" in r.data["blocking_issues"]
