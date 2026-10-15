"""
Django adapter for order extraction.

The extraction logic lives in order_extractor.py (catalog-grounded, provider-neutral).
This module keeps the old entry point, process_chat_messages_sync(), so Celery tasks,
ParsedChatFile records and the Excel export keep working unchanged.

Settings / env:
  LLM_PROVIDER        anthropic | openai | gemini   (default: anthropic)
  LLM_MODEL           optional model override
  <PROVIDER>_API_KEY  ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
  CHAT_SELLER_NAMES   sender names that belong to the business, e.g. ["Aj", "ShopC Srinivasan"]
"""

import os
import time
import random
from typing import List, Dict, Optional, Tuple
from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async

from .schemas import MessageClassification, MessageType, ProcessingStats
from .models import ChatFile, ParsedChatFile
from .utils import save_processed_chat_to_excel
from . import order_extractor as ox

_SKIP_TEXT = {"", "<media omitted>", "you deleted this message", "this message was deleted", "null"}


class DjangoOrderExtractionService:
    """Django-compatible wrapper around order_extractor.run()"""

    def __init__(self):
        self.llm = ox.get_llm(
            provider=getattr(settings, "LLM_PROVIDER", None),
            model=getattr(settings, "LLM_MODEL", None),
        )
        self.default_sellers = set(getattr(settings, "CHAT_SELLER_NAMES", None) or
                                   os.getenv("CHAT_SELLER_NAMES", "Aj").split("|"))
        # used by the legacy helpers below
        self.base_delay = 1.2
        self.max_delay = 120.0
        self.jitter_range = 0.1

    # ─────────────────────────────────────────────────────────────
    # Main entry point for Celery (same signature as before)
    # ─────────────────────────────────────────────────────────────

    def process_chat_messages_sync(
        self,
        messages: List[Dict],
        chat_file_id: str,
        progress_callback=None,
        sellers: Optional[set] = None,
    ) -> Tuple[List[Dict], ProcessingStats]:
        """messages: rows with 'Date', 'Time', 'Phone/Name', 'Message'.
        Returns one processed row per input row (Message_Type, Items, Total_Amount, Notes)."""
        start_time = time.time()
        total = len(messages)
        sellers = set(sellers or self.default_sellers)

        msgs = ox.from_django_rows(messages)
        print(f"[AI] {total} rows, {len(msgs)} with text; sellers={sorted(sellers)}")

        def on_progress(done_chunks, n_chunks):
            if progress_callback:
                done = int(total * done_chunks / n_chunks)
                progress_callback(int(done_chunks / n_chunks * 100), done, total)

        result = ox.run(msgs, self.llm, sellers, on_progress=on_progress)
        print(f"[AI] Catalog: {[p['name'] for p in result['catalog']]}")

        # Map results back onto EVERY input row, including media/deleted rows
        enriched = {id(m["_row"]): r for m, r in zip(msgs, ox.per_message_rows(msgs, result))}
        processed_messages, message_types = [], {}
        for row in messages:
            pm = enriched.get(id(row))
            if pm is None:  # skipped row (<Media omitted>, deleted, empty)
                pm = dict(row, Message_Type="general", Items="", Total_Amount="", Notes="")
            processed_messages.append(pm)
            message_types[pm["Message_Type"]] = message_types.get(pm["Message_Type"], 0) + 1

        orders_df = result["orders"]
        orders_found = orders_df["message_ids"].nunique() if not orders_df.empty else 0
        processing_time = time.time() - start_time

        stats = ProcessingStats(
            total_messages=total,
            message_types=message_types,
            orders_found=int(orders_found),
            confidence_scores={},          # the new pipeline flags rows for review instead
            processing_time=processing_time,
            success_rate=1.0 if total else 0,
        )
        # Full order table (one row per item, with address and review flags) and totals
        # are also available if you want to save them:
        self.last_result = result

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
