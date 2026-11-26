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


class OpenAIResponsesApiTests(SimpleTestCase):
    """OpenAILLM uses the Responses API: newer models (e.g. gpt-5.6-luna) refuse function
    tools on /v1/chat/completions."""

    def llm(self, output):
        from types import SimpleNamespace as NS
        from unittest.mock import MagicMock
        llm = ox.OpenAILLM.__new__(ox.OpenAILLM)
        llm.client, llm.model, llm.temperature = MagicMock(), "gpt-5.6-luna", None
        llm.client.responses.create.return_value = NS(output=output)
        return llm

    def test_forced_function_call_via_responses(self):
        from types import SimpleNamespace as NS
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        llm = self.llm([NS(type="reasoning"), NS(type="function_call", name="emit", arguments='{"x": 3}')])
        assert llm._call("sys", "usr", "emit", schema) == {"x": 3}
        kw = llm.client.responses.create.call_args.kwargs
        assert kw["model"] == "gpt-5.6-luna" and kw["instructions"] == "sys" and kw["input"] == "usr"
        assert kw["tools"] == [{"type": "function", "name": "emit", "description": "Return the result.",
                                "parameters": schema, "strict": False}]
        assert kw["tool_choice"] == {"type": "function", "name": "emit"}
        assert "temperature" not in kw and "reasoning" not in kw
        llm.client.chat.completions.create.assert_not_called()

    def test_no_function_call_raises(self):
        from types import SimpleNamespace as NS
        with self.assertRaises(RuntimeError):
            self.llm([NS(type="message")])._call("s", "u", "emit", {"type": "object"})

    def test_bad_request_is_not_retried(self):
        class BadRequest(Exception):
            status_code = 400
        calls = []

        class Failing(ox.BaseLLM):
            def _call(self, *a):
                calls.append(1)
                raise BadRequest("reasoning_effort not supported")

        with patch("orders.order_extractor.time.sleep") as sleep, self.assertRaises(BadRequest):
            Failing().call("s", "u", "t", {})
        assert len(calls) == 1 and not sleep.called

    def test_rate_limit_is_retried(self):
        class RateLimited(Exception):
            status_code = 429
        calls = []

        class Flaky(ox.BaseLLM):
            def _call(self, *a):
                calls.append(1)
                if len(calls) == 1:
                    raise RateLimited("429")
                return {"ok": True}

        with patch("orders.order_extractor.time.sleep"):
            assert Flaky().call("s", "u", "t", {}) == {"ok": True}
        assert len(calls) == 2
