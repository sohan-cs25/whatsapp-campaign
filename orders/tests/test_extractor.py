from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from orders import order_extractor as ox

MSGS = [
    {"id": "m0", "date": "1/6/26", "time": "9:00 am", "sender": "Aj", "text": "Kesar mango 120/kg"},
    {"id": "m1", "date": "1/6/26", "time": "9:05 am", "sender": "919800000001", "text": "1 kg kesar C710"},
]
CATALOG = [{"id": "kesar_mango", "name": "Kesar Mango", "price": 120.0, "price_per": "kg",
            "first_announced_id": "", "notes": None}]


def order(items, kind="new"):
    return {"message_ids": ["m1"], "sender": "919800000001", "kind": kind, "items": items,
            "block": "C", "unit_no": "710", "flags": []}


class FakeLLM(ox.BaseLLM):
    def __init__(self, orders):
        self.calls, self.orders = [], orders

    def _call(self, system, user, tool_name, schema):
        self.calls.append(tool_name)
        if tool_name == "report_catalog":
            return {"products": CATALOG}
        return {"orders": self.orders, "message_labels": {}}


MANGO = {"product_id": "kesar_mango", "as_written": "kesar", "quantity": 1, "unit": "kg"}
JACK = {"product_id": "OTHER", "other_name": "Jackfruit", "as_written": "jackfruit", "quantity": 1, "unit": "piece"}


class RunTests(SimpleTestCase):
    def test_db_catalog_skips_catalog_pass(self):
        fake = FakeLLM([order([MANGO])])
        ox.run(MSGS, fake, {"Aj"}, catalog=CATALOG)
        assert fake.calls == ["report_orders"]

    def test_chat_catalog_when_none_given(self):
        fake = FakeLLM([order([MANGO])])
        ox.run(MSGS, fake, {"Aj"}, catalog=None)
        assert fake.calls[0] == "report_catalog"

    def test_product_id_column(self):
        df = ox.run(MSGS, FakeLLM([order([MANGO, JACK])]), {"Aj"}, catalog=CATALOG)["orders"]
        assert df.loc[0, "product_id"] == "kesar_mango"
        assert df.loc[1, "product_id"] is None

    def test_itemless_cancellation_kept(self):
        df = ox.run(MSGS, FakeLLM([order([], kind="cancellation")]), {"Aj"}, catalog=CATALOG)["orders"]
        assert len(df) == 1
        assert df.loc[0, "kind"] == "cancellation"
        assert "no_items" in df.loc[0, "flags"].split(",")

    def test_catalog_text_omits_empty_first_announced(self):
        fake = FakeLLM([])
        seen = {}
        orig = fake._call

        def spy(system, user, tool_name, schema):
            seen["system"] = system
            return orig(system, user, tool_name, schema)
        fake._call = spy
        ox.run(MSGS, fake, {"Aj"}, catalog=CATALOG)
        assert "first announced" not in seen["system"]


class ServiceTests(SimpleTestCase):
    def test_service_returns_run_result(self):
        from orders.ai_service import DjangoOrderExtractionService
        rows = [{"Date": "1/6/26", "Time": "9:05 am", "Phone/Name": "919800000001", "Message": "1 kg kesar"}]
        empty = pd.DataFrame(columns=["message_ids"])
        result = {"catalog": [], "orders": empty, "totals": empty, "labels": {}}
        with patch("orders.ai_service.ox.get_llm", return_value=FakeLLM([])), \
             patch("orders.ai_service.ox.run", return_value=result), \
             patch("orders.ai_service.Product.as_catalog", return_value=[]):
            out = DjangoOrderExtractionService().process_chat_messages_sync(rows, chat_file_id="x")
        assert len(out) == 3 and out[2] is result
