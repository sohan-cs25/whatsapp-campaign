"""
Django-adapted AI Order Extraction Service
Handles LLM-powered order extraction using Groq with Django models

KEY FIXES vs original:
1. Batch processing (50 messages per API call) instead of 1-per-call
2. groq_raw client used for batch (no response_model needed)
3. Farm-produce-aware prompt with real examples
4. Python post-processing: _normalize_product() + _normalize_quantity()
   guarantees consistent product names/units regardless of AI output
5. Notes column populated with flat/block numbers
"""

import asyncio
import os
import time
import json
import random
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async

import instructor
import threading
import concurrent.futures
from groq import Groq

from .schemas import MessageClassification, OrderDetails, MessageType, ProcessingStats
from .models import ChatFile, ParsedChatFile
from .utils import save_processed_chat_to_excel


class DjangoOrderExtractionService:
    """Django-compatible service for extracting orders from chat messages using Groq LLM"""

    # ─────────────────────────────────────────────────────────────
    # Product name normalization — applied AFTER AI response
    # Add new aliases here whenever a new product variant appears
    # ─────────────────────────────────────────────────────────────
    PRODUCT_ALIASES = {
        # Chausa Mango variants
        "chausa mango": "Chausa Mango",
        "chausa mangoes": "Chausa Mango",
        "chausa mangos": "Chausa Mango",
        "chausa": "Chausa Mango",
        "mango": "Chausa Mango",       # in Chausa context
        "mangoes": "Chausa Mango",
        "mangos": "Chausa Mango",
        # Dragon Fruit variants
        "dragon fruit": "Dragon Fruit",
        "dragon fruits": "Dragon Fruit",
        "dragon.": "Dragon Fruit",
        "dragonfruit": "Dragon Fruit",
        "dragon": "Dragon Fruit",
        # Sona Masoori Rice variants
        "sona masoori": "Sona Masoori Rice",
        "sona masoori rice": "Sona Masoori Rice",
        "sona masuri": "Sona Masoori Rice",
        "sona masuri rice": "Sona Masoori Rice",
        "sona mansuri": "Sona Masoori Rice",
        "sonamasuri": "Sona Masoori Rice",
        "sonamasoori": "Sona Masoori Rice",
        # Apricot variants
        "apricot": "Apricot",
        "apricots": "Apricot",
        # Pear variants
        "pear": "Pear",
        "pears": "Pear",
        "pear green": "Pear",
        "pears green": "Pear",
        "green pear": "Pear",
        "green pears": "Pear",
        "peers green": "Pear",         # typo in chat
        # Pomegranate variants
        "pomegranate": "Pomegranate",
        "pomegranates": "Pomegranate",
        # Makhana variants
        "makhana": "Makhana",
        "makhanas": "Makhana",
        "fox nuts": "Makhana",
        "fox nut": "Makhana",
        # Lychee variants
        "lychee": "Lychee",
        "lychees": "Lychee",
        "litchi": "Lychee",
        "litchis": "Lychee",
        "lichi": "Lychee",
        # Atta variants
        "atta": "Atta",
        "aata": "Atta",
        "wheat flour": "Atta",
        # Oil variants
        "sesame oil": "Sesame Oil",
        "mustard oil": "Mustard Oil",
        "mustard oil kachi ghani": "Mustard Oil",
        "ground oil": "Groundnut Oil",
        "groundnut oil": "Groundnut Oil",
        "cold press": "Cold Press Oil",
        "cold press all": "Cold Press Oil",
        # Dal variants
        "moong dal": "Moong Dal",
        "moong dal unpolished": "Moong Dal Unpolished",
        "split moong dal yellow": "Split Moong Dal",
        "split moong with skin": "Split Moong Dal With Skin",
        # Other
        "cashew unroasted": "Cashew Unroasted",
        "cashew": "Cashew",
        "ragi": "Ragi",
        "turmeric": "Turmeric",
        "produce": "Produce",
    }

    def __init__(self):
        self.api_key = getattr(settings, 'GROQ_API_KEY', os.getenv("GROQ_API_KEY"))
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in settings or environment variables")

        groq_client = Groq(api_key=self.api_key)
        # instructor client — kept for single-message classify_message()
        self.client = instructor.from_groq(groq_client, mode=instructor.Mode.JSON)
        # raw Groq client — used for batch calls (no response_model needed)
        self.groq_raw = groq_client

        self.model_name = "llama-3.1-8b-instant"
        self.base_delay = 1.2
        self.max_delay = 120.0
        self.max_retries = 3
        self.jitter_range = 0.1
        self.batch_size = 50
        self.retry_delay = 65.0

    # ─────────────────────────────────────────────────────────────
    # Normalization helpers
    # ─────────────────────────────────────────────────────────────

    def _normalize_product(self, name: str) -> str:
        """Map any product name variant to the canonical form."""
        if not name:
            return name
        key = name.strip().lower()
        if key in self.PRODUCT_ALIASES:
            return self.PRODUCT_ALIASES[key]
        # Title Case fallback for unknown products
        return name.strip().title()

    def _normalize_quantity(self, qty) -> str:
        """Ensure quantity always has a unit string."""
        if qty is None:
            return ""
        qty_str = str(qty).strip().lower()
        # Already has a recognisable unit — standardise spelling
        if any(u in qty_str for u in ["kg", "gm", "gram", "litre", "ltr", "lt ", "lt$",
                                       "piece", "pcs", "box", "dozen", "packet"]):
            qty_str = (qty_str
                       .replace("kgs", "kg").replace("gms", "gm")
                       .replace("grams", "gm").replace("gram", "gm")
                       .replace("litre", "ltr").replace("liter", "ltr")
                       .replace("lt ", "ltr").replace(" lt", " ltr"))
            return qty_str.strip()
        # Strip leading dash (AI sometimes returns "- 4kg")
        qty_str = qty_str.lstrip("- ").strip()
        try:
            val = float(qty_str)
            if val < 1 and val > 0:
                return f"{int(val * 1000)} gm"
            return f"{val:g} kg"
        except ValueError:
            return qty_str

    def _extract_context_product(self, messages: List[Dict]) -> str:
        """Scan messages for the most recent seller announcement."""
        keywords = ["price is", "per kg", "per piece", "available",
                    "please share your order", "rs ", "₹", "per dozen",
                    "per box", "we have received", "we will deliver",
                    "share your orders", "we will be delivering"]
        for msg in reversed(messages):
            text = msg.get("Message", "").lower()
            if any(kw in text for kw in keywords):
                return msg.get("Message", "")
        return ""

    # ─────────────────────────────────────────────────────────────
    # BATCH classify
    # ─────────────────────────────────────────────────────────────

    def _classify_batch(self, batch: List[Dict], product_context: str = "") -> List[Dict]:
        """Send a batch of messages in ONE API call. Returns list of dicts."""
        product_hint = f'\nCurrent products being sold: "{product_context}"' if product_context else ""

        messages_text = ""
        for idx, msg in enumerate(batch):
            sender = msg.get('Phone/Name', '')
            text = msg.get('Message', '')
            messages_text += f"\n[{idx}] Sender: {sender}\nMessage: {text}\n"

        prompt = f"""You are analyzing a WhatsApp group for a farm produce home delivery business in India.

HOW THIS GROUP WORKS:
- Seller (Aj) posts product announcements with prices
- Customers reply with their ORDER listing product + quantity + flat/block number
- Flat/block codes like "C1004", "B1101", "D703", "E503", "A-801", "C303" are DELIVERY LOCATIONS not products{product_hint}

CLASSIFICATION RULES:
- order: Message lists products with quantities to buy. Multi-line messages with flat number + items are orders.
- enquiry: Questions about availability/delivery/price with no quantity
- review: Feedback about quality or taste
- address: ONLY a standalone address/flat number with NO products
- announcement: Seller posts about products, prices, delivery schedule
- general: Greetings, <Media omitted>, "You deleted this message", casual chat, seller replies

IMPORTANT — DO NOT hallucinate products:
- Only extract products explicitly mentioned in the message
- If message says "1 kg" with no product name, use the announced product from context
- "You deleted this message" → general
- Flat codes alone (e.g. "D703") are NOT orders unless accompanied by products/quantities

For ORDER messages extract items exactly as mentioned (normalization done separately):
- items: {{"product as written": "quantity with unit"}}
- notes: flat/block/house number (e.g. "C1004", "B802", "E 503", "A-801")
- total_amount: only if explicit Rs/₹ amount stated

QUANTITY FORMAT — always include unit:
"1 kg" not "1", "500 gm" not "500", "1 ltr" not "1"
"2 kgs" → "2 kg", "500 gms" → "500 gm", "1 lt" → "1 ltr"
"1/2 kg" → "0.5 kg"

Return a JSON array, one object per message, EXACT SAME ORDER as input:
[{{
  "index": 0,
  "message_type": "order|enquiry|review|address|announcement|general",
  "confidence": 0.0-1.0,
  "items": {{"product": "quantity unit"}} or null,
  "total_amount": null,
  "notes": "C1004" or null
}}]

Return ONLY the JSON array. No markdown. No explanation.

Messages:
{messages_text}"""

        for attempt in range(self.max_retries):
            try:
                response = self.groq_raw.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4096,
                    temperature=0.1
                )
                raw = response.choices[0].message.content
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                results = json.loads(raw)
                if isinstance(results, list):
                    print(f"[AI] Batch returned {len(results)} results")
                    return results

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(x in err_str for x in [
                    "429", "rate limit", "quota", "resource_exhausted",
                    "too many", "rate_limit_exceeded"
                ])
                if is_rate_limit:
                    print(f"[AI] Rate limit. Waiting {self.retry_delay}s (attempt {attempt+1}/{self.max_retries})")
                    time.sleep(self.retry_delay)
                else:
                    print(f"[AI] Batch error attempt {attempt+1}: {e}")
                    if attempt == self.max_retries - 1:
                        break
                    time.sleep(5)

        print(f"[AI] Batch failed, using fallback for {len(batch)} messages")
        return [
            {"index": i, "message_type": "general", "confidence": 0.0,
             "items": None, "total_amount": None, "notes": None}
            for i in range(len(batch))
        ]

    # ─────────────────────────────────────────────────────────────
    # Main entry point for Celery
    # ─────────────────────────────────────────────────────────────

    def process_chat_messages_sync(
        self,
        messages: List[Dict],
        chat_file_id: str,
        progress_callback=None
    ) -> Tuple[List[Dict], ProcessingStats]:
        """Synchronous batch processing — safe to call directly from Celery."""

        start_time = time.time()
        processed_messages = []
        message_types = {}
        orders_found = 0
        confidence_scores = {}
        successful = 0
        total = len(messages)

        print(f"[AI] Processing {total} messages in batches of {self.batch_size}")

        # Extract product context from ALL messages once
        product_context = self._extract_context_product(messages)
        if product_context:
            print(f"[AI] Product context: {product_context[:80]}")

        batches = [messages[i:i+self.batch_size] for i in range(0, total, self.batch_size)]

        for batch_num, batch in enumerate(batches):
            print(f"[AI] Batch {batch_num+1}/{len(batches)} ({len(batch)} messages)")

            to_classify = []
            skip_indices = set()
            for i, msg in enumerate(batch):
                text = msg.get('Message', '').strip()
                if not text or text in ('<Media omitted>', 'You deleted this message'):
                    skip_indices.add(i)
                else:
                    to_classify.append((i, msg))

            result_map = {}
            if to_classify:
                classify_input = [msg for _, msg in to_classify]
                results = self._classify_batch(classify_input, product_context)
                for r in results:
                    idx = r.get('index', 0)
                    if 0 <= idx < len(to_classify):
                        original_idx = to_classify[idx][0]
                        result_map[original_idx] = r

            for i, message in enumerate(batch):
                if i in skip_indices:
                    pm = message.copy()
                    pm.update({'Message_Type': 'general', 'Items': '',
                               'Total_Amount': '', 'Notes': ''})
                    processed_messages.append(pm)
                    continue

                r = result_map.get(i, {})
                msg_type = r.get('message_type', 'general')
                confidence = max(0.0, min(1.0, float(r.get('confidence', 0.0))))

                pm = message.copy()
                pm.update({
                    'Message_Type': msg_type,
                    'Items': '',
                    'Total_Amount': '',
                    'Notes': r.get('notes') or ''
                })

                if msg_type == 'order' and r.get('items'):
                    # Normalize product names + units via Python (guaranteed)
                    normalized = {
                        self._normalize_product(k): self._normalize_quantity(v)
                        for k, v in r['items'].items()
                        if k and str(k).lower() not in ('', 'null', 'none')
                    }
                    if normalized:
                        pm['Items'] = ', '.join([f"{k}: {v}" for k, v in normalized.items()])
                    if r.get('total_amount'):
                        pm['Total_Amount'] = f"Rs {r['total_amount']}"
                    orders_found += 1

                processed_messages.append(pm)
                message_types[msg_type] = message_types.get(msg_type, 0) + 1
                confidence_scores.setdefault(msg_type, []).append(confidence)
                successful += 1

            if progress_callback:
                done = min((batch_num + 1) * self.batch_size, total)
                progress_callback(int(done / total * 100), done, total)

            if batch_num < len(batches) - 1:
                print(f"[AI] Batch {batch_num+1} done. Waiting 5s...")
                time.sleep(5)

        processing_time = time.time() - start_time
        avg_confidence = {t: sum(s)/len(s) for t, s in confidence_scores.items() if s}

        stats = ProcessingStats(
            total_messages=total,
            message_types=message_types,
            orders_found=orders_found,
            confidence_scores=avg_confidence,
            processing_time=processing_time,
            success_rate=successful / total if total > 0 else 0
        )

        print(f"[AI] Complete. {total} messages, {orders_found} orders in {processing_time:.1f}s")
        print(f"[AI] Type breakdown: {message_types}")
        return processed_messages, stats

    # ─────────────────────────────────────────────────────────────
    # Legacy async method — kept for compatibility
    # ─────────────────────────────────────────────────────────────

    def _is_rate_limit_error(self, error) -> bool:
        error_str = str(error).lower()
        return any(x in error_str for x in [
            "rate limit", "too many requests", "quota exceeded",
            "429", "rate_limit_exceeded", "requests per minute", "rate_limit_error"
        ])

    def _calculate_backoff_delay(self, attempt: int) -> float:
        exponential_delay = self.base_delay * (2 ** attempt)
        capped_delay = min(exponential_delay, self.max_delay)
        jitter = capped_delay * self.jitter_range * (2 * random.random() - 1)
        return max(0.5, capped_delay + jitter)

    def _fallback_classification(self) -> MessageClassification:
        return MessageClassification(
            message_type=MessageType.GENERAL,
            confidence=0.0,
            extracted_order=None,
            reasoning="Classification failed - using fallback"
        )

    @sync_to_async
    def _save_processed_file(self, processed_messages: List[Dict], output_path: str) -> bool:
        return save_processed_chat_to_excel(processed_messages, output_path)

    @sync_to_async
    def _update_chat_file_status(self, chat_file_id: str, is_processed: bool, error: str = ""):
        try:
            chat_file = ChatFile.objects.get(id=chat_file_id)
            chat_file.is_processed = is_processed
            chat_file.processed_at = timezone.now() if is_processed else None
            if error:
                chat_file.processing_error = error[:500]
            chat_file.save()
            return chat_file
        except ChatFile.DoesNotExist:
            raise ValueError(f"ChatFile {chat_file_id} not found")

    @sync_to_async
    def _create_parsed_file_record(self, chat_file, processed_messages: List[Dict],
                                    stats: ProcessingStats, output_filename: str):
        return ParsedChatFile.objects.create(
            user=chat_file.user,
            chatfile=chat_file,
            file_name=output_filename,
            processed_file_path=f"processedchatfile/{output_filename}",
            total_messages=stats.total_messages,
            total_orders=stats.orders_found,
            total_queries=stats.message_types.get('enquiry', 0)
        )


# Global service instance
django_ai_service = DjangoOrderExtractionService()
