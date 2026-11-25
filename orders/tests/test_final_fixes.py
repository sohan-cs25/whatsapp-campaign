import os
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APITestCase

from orders.models import ChatFile, Order, ParsedChatFile, ValidatedFile
from orders.tests.helpers import make_products, make_user


class LegacyOwnershipTests(APITestCase):
    def test_order_without_user_visible_via_validated_file(self):
        user = make_user()
        vf = ValidatedFile.objects.create(user=user, file_name="v.csv", filepath="validatedchatfile/v.csv",
                                          filetype="csv")
        order = Order.objects.create(validated_file=vf, number="919800000001", order_items="Apples:2",
                                     amount="100=100")
        assert order.user is None
        self.client.force_authenticate(user)
        ids = [o["id"] for o in self.client.get("/api/orders/orders/").data["results"]]
        assert str(order.id) in ids


class ProcessRetryTests(TestCase):
    def test_retry_after_parsed_file_exists(self):
        from orders.tasks import process_chat_file
        user = make_user()
        make_products()
        rel = "chatfile/test_retry_chat.txt"
        path = os.path.join(settings.ORDERS_MEDIA_ROOT, rel)
        with open(path, "w", encoding="utf-8") as f:
            f.write("01/06/2026, 9:05 am - +91 98000 00001: 1 kg kesar C710\n")
        self.addCleanup(os.remove, path)
        chat = ChatFile.objects.create(user=user, filename="test_retry_chat.txt", filepath=rel, filetype="text")
        ParsedChatFile.objects.create(user=user, chatfile=chat, file_name="old.xlsx",
                                      processed_file_path="processedchatfile/old.xlsx")  # left by a failed attempt
        stats = SimpleNamespace(total_messages=1, orders_found=0, message_types={}, processing_time=0.1,
                                success_rate=1.0)
        fake = lambda messages, chat_file_id: (messages, stats, {"orders": pd.DataFrame()})
        with patch("orders.ai_service.django_ai_service.process_chat_messages_sync", side_effect=fake), \
             patch("orders.tasks.save_enhanced_messages_to_excel", return_value=True):
            result = process_chat_file.apply(args=[str(chat.id)], retries=3).get()
        assert result["success"], result
        assert ParsedChatFile.objects.filter(chatfile=chat).count() == 1
