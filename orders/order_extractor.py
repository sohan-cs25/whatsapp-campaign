"""
Catalog-grounded order extraction for WhatsApp group-commerce chats.

Pipeline
  1. parse_chat()       WhatsApp export -> list of messages with stable ids (m0, m1, ...)
  2. build_catalog()    ONE LLM call over the SELLER's messages only -> list of
                        products on offer (id, name, price, unit, when announced)
  3. extract_orders()   LLM over the conversation in time-ordered chunks. The catalog
                        is passed as a closed enum, so "lichee", "leechee", "lychi"
                        are mapped by the model to product_id "shahi_lychee" at
                        extraction time. No hand-written alias table.
  4. postprocess()      Deterministic Python: unit conversion, address formatting,
                        filling missing addresses from the sender's other orders,
                        review flags, totals.

The LLM is behind a tiny interface (call(system, user, tool_name, schema) -> dict),
so swapping Claude / GPT / Gemini is one env var: LLM_PROVIDER=anthropic|openai|gemini
(optional LLM_MODEL). See get_llm().
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# 1. Parsing
# ─────────────────────────────────────────────────────────────────────────────

# WhatsApp exports often use a narrow no-break space (\u202f) before am/pm.
_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s(\d{1,2}:\d{2})[\s\u202f]?([ap]m)\s-\s(.*)$", re.I
)
_SKIP_TEXT = {"<media omitted>", "you deleted this message", "this message was deleted", "null"}


def parse_chat(text: str) -> List[Dict]:
    """Return messages as dicts with keys: id, date, time, sender, text."""
    msgs: List[Dict] = []
    for line in text.splitlines():
        m = _LINE.match(line)
        if not m:
            if msgs:  # continuation of a multi-line message
                msgs[-1]["text"] += "\n" + line
            continue
        date, hhmm, ampm, rest = m.groups()
        if ": " not in rest:  # system line: "You added X", "Y joined", "You're now an admin"
            msgs.append({"date": date, "time": f"{hhmm} {ampm}", "sender": None, "text": rest})
            continue
        sender, body = rest.split(": ", 1)
        msgs.append({"date": date, "time": f"{hhmm} {ampm}", "sender": sender.strip(), "text": body})

    out = []
    for m in msgs:
        t = m["text"].replace("<This message was edited>", "").strip()
        if m["sender"] is None or not t or t.lower() in _SKIP_TEXT:
            continue
        m["text"] = t
        m["id"] = f"m{len(out)}"
        out.append(m)
    return out


def from_django_rows(rows: List[Dict]) -> List[Dict]:
    """Adapter for the existing pipeline's {'Date','Time','Phone/Name','Message'} rows."""
    out = []
    for r in rows:
        t = str(r.get("Message", "")).replace("<This message was edited>", "").strip()
        if not t or t.lower() in _SKIP_TEXT:
            continue
        out.append({"id": f"m{len(out)}", "date": r.get("Date", ""), "time": r.get("Time", ""),
                    "sender": r.get("Phone/Name", ""), "text": t, "_row": r})
    return out


def _fmt(msgs: List[Dict], sellers: set) -> str:
    lines = []
    for m in msgs:
        who = f"{m['sender']} [SELLER]" if m["sender"] in sellers else m["sender"]
        lines.append(f"[{m['id']}] {m['date']} {m['time']} | {who}: {m['text']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 2. LLM interface
# ─────────────────────────────────────────────────────────────────────────────

class BaseLLM:
    """Provider-neutral interface. The pipeline only calls .call(); each provider
    implements _call(system, user, tool_name, schema) -> dict. Retries live here."""

    max_retries = 4

    def call(self, system: str, user: str, tool_name: str, schema: Dict) -> Dict:
        for attempt in range(self.max_retries):
            try:
                return self._call(system, user, tool_name, schema)
            except Exception as e:  # rate limits, transient 5xx, malformed JSON
                if attempt == self.max_retries - 1:
                    raise
                rate_limited = "429" in str(e) or "rate" in str(e).lower()
                wait = (15 if rate_limited else 2) * 2 ** attempt
                print(f"[LLM] {type(e).__name__}: {str(e)[:200]} — retry in {wait}s")
                time.sleep(wait)

    def _call(self, system: str, user: str, tool_name: str, schema: Dict) -> Dict:
        raise NotImplementedError


class AnthropicLLM(BaseLLM):
    """Forced tool use.  Env: ANTHROPIC_API_KEY.  pip install anthropic"""

    default_model = "claude-sonnet-5-5"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model or self.default_model

    def _call(self, system, user, tool_name, schema):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            
            system=system,
            tools=[{"name": tool_name, "description": "Return the result.", "input_schema": schema}],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("Model returned no tool call")


class OpenAILLM(BaseLLM):
    """Forced function calling.  Env: OPENAI_API_KEY.  pip install openai
    temperature is left unset by default: GPT-5 / o-series reasoning models reject it."""

    default_model = "gpt-5"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None,
                 temperature: Optional[float] = None):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model or self.default_model
        self.temperature = temperature

    def _call(self, system, user, tool_name, schema):
        extra = {"temperature": self.temperature} if self.temperature is not None else {}
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[{"type": "function", "function": {
                "name": tool_name, "description": "Return the result.", "parameters": schema}}],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            **extra,
        )
        calls = resp.choices[0].message.tool_calls
        if not calls:
            raise RuntimeError("Model returned no tool call")
        return json.loads(calls[0].function.arguments)


def _to_gemini_schema(s):
    """Gemini's response_schema is an OpenAPI subset: no type lists, no null in enums.
    Convert {"type": ["string","null"]} -> {"type": "string", "nullable": true}."""
    if isinstance(s, list):
        return [_to_gemini_schema(x) for x in s]
    if not isinstance(s, dict):
        return s
    out = {}
    for k, v in s.items():
        if k == "type" and isinstance(v, list):
            non_null = [t for t in v if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in v:
                out["nullable"] = True
        elif k == "enum":
            out["enum"] = [x for x in v if x is not None]
        elif k in ("properties",):
            out[k] = {pk: _to_gemini_schema(pv) for pk, pv in v.items()}
        else:
            out[k] = _to_gemini_schema(v)
    return out


class GeminiLLM(BaseLLM):
    """JSON-schema constrained output.  Env: GEMINI_API_KEY (or GOOGLE_API_KEY).
    pip install google-genai"""

    default_model = "gemini-2.5-pro"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        from google import genai
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.model = model or self.default_model

    def _call(self, system, user, tool_name, schema):
        from google.genai import types
        resp = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                
                response_mime_type="application/json",
                response_schema=_to_gemini_schema(schema),
            ),
        )
        if not resp.text:
            raise RuntimeError("Model returned empty response")
        return json.loads(resp.text)


PROVIDERS = {"anthropic": AnthropicLLM, "openai": OpenAILLM, "gemini": GeminiLLM}


def get_llm(provider: Optional[str] = None, model: Optional[str] = None,
            api_key: Optional[str] = None) -> BaseLLM:
    """Choose provider from args, else env LLM_PROVIDER (anthropic|openai|gemini) and
    LLM_MODEL. If api_key is None, each SDK reads its own key env var."""
    provider = (provider or os.getenv("LLM_PROVIDER") or "anthropic").lower()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider '{provider}'; choose from {sorted(PROVIDERS)}")
    return PROVIDERS[provider](model=model or os.getenv("LLM_MODEL"), api_key=api_key)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pass 1 — catalog from seller messages
# ─────────────────────────────────────────────────────────────────────────────

CATALOG_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "snake_case, unique, e.g. 'kesar_mango'"},
                    "name": {"type": "string", "description": "Canonical display name, e.g. 'Kesar Mango'"},
                    "price": {"type": ["number", "null"]},
                    "price_per": {"type": ["string", "null"], "description": "e.g. 'kg', '250 g box', 'litre'"},
                    "first_announced_id": {"type": "string", "description": "message id, e.g. 'm0'"},
                    "notes": {"type": ["string", "null"], "description": "origin, variety, delivery day"},
                },
                "required": ["id", "name", "price", "price_per", "first_announced_id"],
            },
        }
    },
    "required": ["products"],
}

CATALOG_SYSTEM = """You read the SELLER's messages from an Indian WhatsApp group where a small farm-produce \
business sells fruit, grains, oils and staples. List every distinct product the seller offers or says is \
available, with price if stated. Keep varieties separate (Kesar mango and Chausa mango are different products; \
normal atta and khapli atta are different). Never invent a product the seller did not mention. \
If a later message changes a price, use the latest price."""


def build_catalog(msgs: List[Dict], sellers: set, llm) -> List[Dict]:
    seller_msgs = [m for m in msgs if m["sender"] in sellers]
    if not seller_msgs:
        return []
    out = llm.call(CATALOG_SYSTEM, _fmt(seller_msgs, sellers), "report_catalog", CATALOG_SCHEMA)
    seen, catalog = set(), []
    for p in out.get("products", []):
        if p.get("id") and p["id"] not in seen:
            seen.add(p["id"])
            catalog.append(p)
    return catalog


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pass 2 — orders, grounded on the catalog
# ─────────────────────────────────────────────────────────────────────────────

UNITS = ["kg", "g", "l", "ml", "box", "piece", "packet", "dozen", "bunch"]


def _orders_schema(product_ids: List[str]) -> Dict:
    return {
        "type": "object",
        "properties": {
            "orders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "message_ids": {"type": "array", "items": {"type": "string"}},
                        "sender": {"type": "string"},
                        "kind": {"type": "string", "enum": ["new", "addition", "cancellation"]},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "product_id": {"type": "string", "enum": product_ids + ["OTHER"]},
                                    "other_name": {"type": ["string", "null"],
                                                   "description": "Only when product_id is OTHER: clean canonical name"},
                                    "as_written": {"type": "string"},
                                    "quantity": {"type": ["number", "null"]},
                                    "unit": {"type": ["string", "null"], "enum": UNITS + [None]},
                                },
                                "required": ["product_id", "as_written", "quantity", "unit"],
                            },
                        },
                        "block": {"type": ["string", "null"], "description": "Tower/block letter, e.g. 'C'"},
                        "unit_no": {"type": ["string", "null"], "description": "Flat/house number, e.g. '710'"},
                        "phone": {"type": ["string", "null"]},
                        "flags": {"type": "array", "items": {"type": "string", "enum": [
                            "ambiguous_product", "missing_quantity", "placed_before_seller_accepted",
                            "seller_declined", "unclear"]}},
                    },
                    "required": ["message_ids", "sender", "kind", "items", "block", "unit_no", "flags"],
                },
            },
            "message_labels": {
                "type": "object",
                "description": "Non-order message ids grouped by type",
                "properties": {k: {"type": "array", "items": {"type": "string"}}
                               for k in ["enquiry", "review", "payment", "complaint"]},
            },
        },
        "required": ["orders"],
    }


ORDERS_SYSTEM = """You extract customer ORDERS from an Indian WhatsApp group for a small farm-produce \
delivery business. Messages marked [SELLER] are from the business.

PRODUCT CATALOG (map every item to one of these ids):
{catalog}

Grocery items ordered that are NOT in the catalog: use product_id "OTHER" and give other_name. \
Reuse these names when they fit, for consistency: {other_names}

Rules:
- Customers misspell freely: lychee / lichi / lichee / leechee / litchi / lychi / leeches are all the same \
fruit. Map spelling variants, plurals, and short forms ("kesar", "chausa", "imam pasand") to the catalog id.
- A bare quantity ("1 kg please", "half kg for me") refers to the product of the most recent [SELLER] \
announcement before it. If several products are active and you cannot tell, pick the most likely one and add \
flag "ambiguous_product".
- One order may span messages (items in one, flat number in the next). Merge them and list all message_ids.
- "Can you give me half kg more" → kind "addition". "Cancel my order" → kind "cancellation".
- Addresses: "C710", "C 710.", "c-710" → block C, unit_no 710. "I block @ 335" → block I, unit_no 335. \
"Hno: 13", "house number 65", "62 SV", "House 29" → block null, unit_no the number. \
A 10-digit number is a phone, not an address. Never treat an address number as a price or quantity.
- Quantities: "1/2 kg", "half kg" → 0.5 kg; "500gm" → 500 g; "1 box" → 1 box.
- If the seller said orders are not being accepted yet (e.g. "we will take orders once the farmer \
confirms"), still extract the order but flag "placed_before_seller_accepted". If the seller says the item \
is unavailable, flag "seller_declined".
- Payment confirmations, reviews, delivery complaints and questions are NOT orders; list them in message_labels.
- Only extract orders from messages in the EXTRACT section. The CONTEXT section is earlier chat for reference."""


@dataclass
class ExtractConfig:
    chunk_size: int = 150      # messages to extract from per call
    overlap: int = 25          # earlier messages shown as read-only context
    sellers: set = field(default_factory=set)


def extract_orders(msgs: List[Dict], catalog: List[Dict], llm, cfg: ExtractConfig,
                   on_progress: Optional[Callable[[int, int], None]] = None) -> Dict:
    product_ids = [p["id"] for p in catalog]
    schema = _orders_schema(product_ids)
    catalog_txt = "\n".join(
        f"- {p['id']}: {p['name']}"
        + (f" (Rs {p['price']} per {p['price_per']})" if p.get("price") else "")
        + f" — first announced {p['first_announced_id']}"
        + (f" — {p['notes']}" if p.get("notes") else "")
        for p in catalog
    ) or "(no announced products)"

    other_names: List[str] = []
    all_orders, labels = [], defaultdict(list)
    n_chunks = max(1, -(-len(msgs) // cfg.chunk_size))

    for c in range(n_chunks):
        start, end = c * cfg.chunk_size, min((c + 1) * cfg.chunk_size, len(msgs))
        context = msgs[max(0, start - cfg.overlap):start]
        # Always include seller announcements that precede the chunk, so a bare "1 kg"
        # at the top of a chunk can still be resolved.
        ctx_ids = {m["id"] for m in context}
        earlier_seller = [m for m in msgs[:start] if m["sender"] in cfg.sellers and m["id"] not in ctx_ids][-10:]
        user = ""
        if earlier_seller or context:
            user += "=== CONTEXT (do not extract) ===\n" + _fmt(earlier_seller + context, cfg.sellers) + "\n\n"
        user += "=== EXTRACT ===\n" + _fmt(msgs[start:end], cfg.sellers)

        system = ORDERS_SYSTEM.format(catalog=catalog_txt, other_names=", ".join(other_names) or "(none yet)")
        out = llm.call(system, user, "report_orders", schema)

        valid_ids = {m["id"] for m in msgs[start:end]}
        for o in out.get("orders", []):
            o["message_ids"] = [i for i in o.get("message_ids", []) if i in valid_ids]
            if not o["message_ids"]:
                continue  # model extracted from context section — drop
            for it in o.get("items", []):
                if it.get("product_id") == "OTHER" and it.get("other_name"):
                    name = it["other_name"].strip().title()
                    it["other_name"] = name
                    if name not in other_names:
                        other_names.append(name)
            all_orders.append(o)
        for k, ids in (out.get("message_labels") or {}).items():
            labels[k].extend(i for i in ids if i in valid_ids)

        if on_progress:
            on_progress(c + 1, n_chunks)

    return {"orders": all_orders, "labels": dict(labels)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. Deterministic post-processing
# ─────────────────────────────────────────────────────────────────────────────

_TO_BASE = {"kg": ("g", 1000), "g": ("g", 1), "l": ("ml", 1000), "ml": ("ml", 1)}


def _address(block, unit_no) -> Optional[str]:
    unit_no = re.sub(r"\D", "", str(unit_no or ""))
    if not unit_no:
        return None
    block = re.sub(r"[^A-Za-z]", "", str(block or "")).upper()
    return f"{block}-{unit_no}" if block else f"House {unit_no}"


def postprocess(result: Dict, catalog: List[Dict], msgs: List[Dict]) -> pd.DataFrame:
    by_id = {m["id"]: m for m in msgs}
    names = {p["id"]: p["name"] for p in catalog}
    known_ids = set(names)

    # Sender -> address directory, built from every order in the chat.
    directory: Dict[str, Counter] = defaultdict(Counter)
    for o in result["orders"]:
        addr = _address(o.get("block"), o.get("unit_no"))
        if addr:
            directory[o["sender"]][addr] += 1

    rows = []
    for o in result["orders"]:
        flags = list(o.get("flags") or [])
        addr = _address(o.get("block"), o.get("unit_no"))
        if not addr and directory.get(o["sender"]):
            addr = directory[o["sender"]].most_common(1)[0][0]
            flags.append("address_from_other_orders")
        if not addr:
            flags.append("no_address")
        first = by_id[o["message_ids"][0]]

        for it in o.get("items", []):
            pid = it.get("product_id")
            item_flags = list(flags)
            if pid == "OTHER" or pid not in known_ids:
                if pid not in ("OTHER", None):
                    item_flags.append("unknown_product_id")
                product = it.get("other_name") or it.get("as_written", "").strip().title()
                in_catalog = False
            else:
                product, in_catalog = names[pid], True

            qty, unit = it.get("quantity"), it.get("unit")
            if qty is None or unit is None:
                item_flags.append("missing_quantity")
            base_unit, mult = _TO_BASE.get(unit, (unit, 1))
            sign = -1 if o.get("kind") == "cancellation" else 1

            rows.append({
                "date": first["date"], "time": first["time"], "sender": o["sender"],
                "address": addr, "phone": o.get("phone"),
                "product": product, "in_catalog": in_catalog, "as_written": it.get("as_written"),
                "quantity": qty, "unit": unit,
                "base_qty": sign * qty * mult if qty is not None else None, "base_unit": base_unit,
                "kind": o.get("kind"), "message_ids": ",".join(o["message_ids"]),
                "flags": ",".join(sorted(set(item_flags))),
                "needs_review": bool(set(item_flags) - {"address_from_other_orders"}),
            })
    return pd.DataFrame(rows)


def totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return (df.dropna(subset=["base_qty"])
              .groupby(["product", "base_unit"], as_index=False)
              .agg(total=("base_qty", "sum"), orders=("sender", "count"))
              .sort_values("product"))


# ─────────────────────────────────────────────────────────────────────────────
# 6. One-call entry point
# ─────────────────────────────────────────────────────────────────────────────

def run(msgs: List[Dict], llm, sellers: set, cfg: Optional[ExtractConfig] = None, on_progress=None):
    cfg = cfg or ExtractConfig()
    cfg.sellers = set(sellers)
    if not msgs:  # nothing to extract — don't call the LLM
        empty = postprocess({"orders": [], "labels": {}}, [], [])
        return {"catalog": [], "orders": empty, "totals": empty, "labels": {}}
    catalog = build_catalog(msgs, cfg.sellers, llm)
    result = extract_orders(msgs, catalog, llm, cfg, on_progress)
    df = postprocess(result, catalog, msgs)
    return {"catalog": catalog, "orders": df, "totals": totals(df), "labels": result["labels"]}


def per_message_rows(msgs: List[Dict], run_out: Dict) -> List[Dict]:
    """Map results back onto the old per-message format (Message_Type / Items / Notes)
    so the existing Excel export keeps working."""
    df, labels = run_out["orders"], run_out["labels"]
    label_of = {i: k for k, ids in labels.items() for i in ids}
    items_of, addr_of = defaultdict(list), {}
    for _, r in df.iterrows():
        mid = r["message_ids"].split(",")[0]
        items_of[mid].append(f"{r['product']}: {r['quantity']:g} {r['unit']}" if r["quantity"] is not None
                             else r["product"])
        addr_of[mid] = r["address"] or ""
    rows = []
    for m in msgs:
        base = dict(m.get("_row") or {"Date": m["date"], "Time": m["time"],
                                      "Phone/Name": m["sender"], "Message": m["text"]})
        is_order = m["id"] in items_of
        base.update({"Message_Type": "order" if is_order else label_of.get(m["id"], "general"),
                     "Items": ", ".join(items_of.get(m["id"], [])), "Total_Amount": "",
                     "Notes": addr_of.get(m["id"], "")})
        rows.append(base)
    return rows


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    sellers = set(sys.argv[2].split("|")) if len(sys.argv) > 2 else {"Aj"}
    msgs = parse_chat(open(path, encoding="utf-8").read())
    out = run(msgs, get_llm(), sellers, on_progress=lambda i, n: print(f"chunk {i}/{n}"))
    print(json.dumps(out["catalog"], indent=2, ensure_ascii=False))
    print(out["totals"].to_string(index=False))
    out["orders"].to_excel(path.rsplit(".", 1)[0] + "_orders.xlsx", index=False)
