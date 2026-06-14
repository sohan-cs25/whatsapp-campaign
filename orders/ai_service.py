"""
Django-adapted AI Order Extraction Service
Uses batch processing — classifies ALL messages in a single API call.

ACTIVE PROVIDER : Groq (llama-3.1-8b-instant)
INACTIVE PROVIDER: Google Gemini (gemini-2.0-flash) — commented out
"""

import os
import time
import json
import concurrent.futures
from typing import List, Dict, Tuple

from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async

# ─────────────────────────────────────────────────────────────
# ACTIVE: Groq
# ─────────────────────────────────────────────────────────────
import instructor
from groq import Groq

# ─────────────────────────────────────────────────────────────
# INACTIVE: Google Gemini  ← uncomment to switch back
# ─────────────────────────────────────────────────────────────
# from google import genai
# from google.genai import types

from .schemas import MessageClassification, OrderDetails, MessageType, ProcessingStats
from .models import ChatFile, ParsedChatFile
from .utils import save_processed_chat_to_excel


class DjangoOrderExtractionService:
    """
    Extracts orders from WhatsApp chat messages using batch processing.
    Sends up to 50 messages per API call to stay within rate limits.
    """

    def __init__(self):

        # ─────────────────────────────────────────────────────
        # ACTIVE: Groq client setup
        # ─────────────────────────────────────────────────────
        self.api_key = getattr(settings, 'GROQ_API_KEY', os.getenv("GROQ_API_KEY"))
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in settings or environment variables")

        groq_client = Groq(api_key=self.api_key)
        self.client = instructor.from_groq(groq_client, mode=instructor.Mode.JSON)
        self.model_name = "llama-3.1-8b-instant"

        # ─────────────────────────────────────────────────────
        # INACTIVE: Gemini client setup  ← uncomment to switch back
        # ─────────────────────────────────────────────────────
        # self.api_key = getattr(settings, 'GEMINI_API_KEY', os.getenv("GEMINI_API_KEY"))
        # if not self.api_key:
        #     raise ValueError("GEMINI_API_KEY not found in settings or environment variables")
        # self.gemini_client = genai.Client(api_key=self.api_key)
        # self.gemini_model = "gemini-2.0-flash"

        self.batch_size = 50      # messages per API call
        self.retry_delay = 65.0   # wait 65s on rate limit
        self.max_retries = 3

    # ─────────────────────────────────────────────────────────────
    # BATCH classify — sends up to 50 messages in ONE API call
    # ─────────────────────────────────────────────────────────────

    def _classify_batch(self, batch: List[Dict]) -> List[Dict]:
        """
        Send a batch of messages to the LLM in a single API call.
        Returns a list of classification dicts matching input order.
        """
        messages_text = ""
        for idx, msg in enumerate(batch):
            sender = msg.get('Phone/Name', '')
            text = msg.get('Message', '')
            messages_text += f"\n[{idx}] Sender: {sender}\nMessage: {text}\n"

        prompt = f"""You are a WhatsApp group chat analyzer for an order processing system.

Classify each numbered message below. Categories:
- order: Customer placing an order with specific product names AND quantities
- enquiry: Questions about products, prices, availability
- review: Customer feedback, complaints, testimonials
- address: Delivery address or location details
- announcement: Business announcements, promotions
- general: Greetings, thanks, casual chat

For ORDER messages extract items as a dict of product->quantity.

Return a JSON array with one object per message, in the SAME ORDER as input.
Each object must have:
{{
  "index": <number matching input>,
  "message_type": "order|enquiry|review|address|announcement|general",
  "confidence": 0.0-1.0,
  "items": {{"product": quantity}} or null,
  "total_amount": number or null,
  "notes": "string or null"
}}

Return ONLY the JSON array, no markdown, no extra text.

Messages to classify:
{messages_text}"""

        for attempt in range(self.max_retries):
            try:
                # ─────────────────────────────────────────────
                # ACTIVE: Groq API call
                # ─────────────────────────────────────────────
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4096,
                    temperature=0.1
                )
                raw = response.choices[0].message.content

                # ─────────────────────────────────────────────
                # INACTIVE: Gemini API call  ← uncomment to switch back
                # ─────────────────────────────────────────────
                # response = self.gemini_client.models.generate_content(
                #     model=self.gemini_model,
                #     contents=prompt,
                #     config=types.GenerateContentConfig(
                #         temperature=0.1,
                #         max_output_tokens=4096,
                #         response_mime_type="application/json",
                #     ),
                # )
                # raw = response.text

                # Strip markdown fences if present
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()

                results = json.loads(raw)
                if isinstance(results, list):
                    return results

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(x in err_str for x in [
                    "429", "rate limit", "quota", "resource_exhausted",
                    "too many", "rate_limit_exceeded"
                ])

                if is_rate_limit:
                    print(f"[AI] Rate limit on batch. Waiting {self.retry_delay}s (attempt {attempt+1}/{self.max_retries})")
                    time.sleep(self.retry_delay)
                else:
                    print(f"[AI] Batch error attempt {attempt+1}: {e}")
                    if attempt == self.max_retries - 1:
                        break
                    time.sleep(5)

        # Fallback: return general for all messages in batch
        print(f"[AI] Batch failed after retries, using fallback for {len(batch)} messages")
        return [
            {"index": i, "message_type": "general", "confidence": 0.0,
             "items": None, "total_amount": None, "notes": "batch failed"}
            for i in range(len(batch))
        ]

    # ─────────────────────────────────────────────────────────────
    # process_chat_messages_sync — main entry point for Celery
    # ─────────────────────────────────────────────────────────────

    def process_chat_messages_sync(
        self,
        messages: List[Dict],
        chat_file_id: str,
        progress_callback=None
    ) -> Tuple[List[Dict], ProcessingStats]:
        """
        Process all messages using batch API calls.
        Synchronous — safe to call directly from Celery tasks.
        """
        start_time = time.time()
        processed_messages = []
        message_types = {}
        orders_found = 0
        confidence_scores = {}
        successful = 0
        total = len(messages)

        print(f"[AI] Processing {total} messages in batches of {self.batch_size}")

        batches = [messages[i:i+self.batch_size] for i in range(0, total, self.batch_size)]

        for batch_num, batch in enumerate(batches):
            print(f"[AI] Batch {batch_num+1}/{len(batches)} ({len(batch)} messages)")

            # Separate empty messages from ones to classify
            to_classify = []
            empty_indices = set()
            for i, msg in enumerate(batch):
                if not msg.get('Message', '').strip():
                    empty_indices.add(i)
                else:
                    to_classify.append((i, msg))

            # Classify non-empty messages
            result_map = {}
            if to_classify:
                classify_input = [msg for _, msg in to_classify]
                results = self._classify_batch(classify_input)

                for r in results:
                    idx = r.get('index', 0)
                    if 0 <= idx < len(to_classify):
                        original_idx = to_classify[idx][0]
                        result_map[original_idx] = r

            # Build processed messages for this batch
            for i, message in enumerate(batch):
                if i in empty_indices:
                    pm = message.copy()
                    pm.update({'Message_Type': 'general', 'Items': '', 'Total_Amount': ''})
                    processed_messages.append(pm)
                    continue

                r = result_map.get(i, {})
                msg_type = r.get('message_type', 'general')
                confidence = float(r.get('confidence', 0.0))
                confidence = max(0.0, min(1.0, confidence))

                pm = message.copy()
                pm.update({'Message_Type': msg_type, 'Items': '', 'Total_Amount': ''})

                if msg_type == 'order' and r.get('items'):
                    items_str = ', '.join([f"{k}: {v}" for k, v in r['items'].items()])
                    pm['Items'] = items_str
                    if r.get('total_amount'):
                        pm['Total_Amount'] = f"${r['total_amount']}"
                    orders_found += 1

                processed_messages.append(pm)
                message_types[msg_type] = message_types.get(msg_type, 0) + 1
                confidence_scores.setdefault(msg_type, []).append(confidence)
                successful += 1

            # Progress update
            if progress_callback:
                done = min((batch_num + 1) * self.batch_size, total)
                progress_callback(int(done / total * 100), done, total)

            # Pause between batches to respect rate limits
            if batch_num < len(batches) - 1:
                print(f"[AI] Batch {batch_num+1} done. Waiting 5s before next batch...")
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
        return processed_messages, stats

    # ─────────────────────────────────────────────────────────────
    # Django async helpers — kept for compatibility
    # ─────────────────────────────────────────────────────────────

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
    def _create_parsed_file_record(self, chat_file, processed_messages, stats, output_filename):
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
