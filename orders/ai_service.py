"""
Django-adapted AI Order Extraction Service
Handles LLM-powered order extraction using Groq with Django models
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
from groq import Groq

from .schemas import MessageClassification, OrderDetails, MessageType, ProcessingStats
from .models import ChatFile, ParsedChatFile
from .utils import save_processed_chat_to_excel


class DjangoOrderExtractionService:
    """Django-compatible service for extracting orders from chat messages using Groq LLM"""

    def __init__(self):
        self.api_key = getattr(settings, 'GROQ_API_KEY', os.getenv("GROQ_API_KEY"))
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in settings or environment variables")

        # Initialize Groq client with instructor
        groq_client = Groq(api_key=self.api_key)
        self.client = instructor.from_groq(groq_client, mode=instructor.Mode.JSON)

        # Enhanced rate limiting configuration
        self.base_delay = 1.2  # Base delay between requests (increased for Django)
        self.max_delay = 120.0  # Maximum delay cap
        self.max_retries = 5  # Maximum retries for rate limits
        self.jitter_range = 0.1  # Random jitter factor
        self.batch_size = 10  # Process messages in batches

    def _is_rate_limit_error(self, error) -> bool:
        """Check if error is related to rate limiting"""
        error_str = str(error).lower()
        rate_limit_indicators = [
            "rate limit", "too many requests", "quota exceeded",
            "429", "rate_limit_exceeded", "requests per minute",
            "rate_limit_error"
        ]
        return any(indicator in error_str for indicator in rate_limit_indicators)

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter"""
        # Exponential backoff: base_delay * 2^attempt
        exponential_delay = self.base_delay * (2 ** attempt)

        # Cap at max_delay
        capped_delay = min(exponential_delay, self.max_delay)

        # Add random jitter to prevent thundering herd
        jitter = capped_delay * self.jitter_range * (2 * random.random() - 1)

        # Ensure minimum delay of 0.5 seconds
        final_delay = max(0.5, capped_delay + jitter)

        return final_delay

    def _fallback_classification(self) -> MessageClassification:
        """Return fallback classification when all retries fail"""
        return MessageClassification(
            message_type=MessageType.GENERAL,
            confidence=0.0,
            extracted_order=None,
            reasoning="Classification failed - using fallback"
        )

    async def classify_message(self, message_text: str, sender: str = "", context: str = "") -> MessageClassification:
        """
        Classify a single message using Groq LLM with enhanced rate limit handling

        Args:
            message_text: The message content to classify
            sender: Message sender name/phone
            context: Additional context if needed

        Returns:
            MessageClassification with type, confidence, and extracted order details
        """
        for attempt in range(self.max_retries):
            try:
                # Add base delay to respect rate limits
                await asyncio.sleep(self.base_delay)

                # Enhanced prompt with better context
                system_prompt = """You are a WhatsApp group chat analyzer for an order processing system.

Classify each message into one of these categories:
- order: Customer placing an order for products (includes quantities)
- enquiry: Questions about products, prices, availability, how to order
- review: Customer feedback, reviews, complaints, or testimonials
- address: Delivery address information or location details
- announcement: Business announcements, updates, promotions
- general: General conversation, greetings, thanks, casual chat

For ORDER messages, extract:
- items: Dictionary of product names and exact quantities {"product": quantity}
- customer_name: If mentioned in the message
- total_amount: If a price/total is mentioned
- delivery_address: If address details are provided
- phone_number: If different from sender
- notes: Any special instructions or notes

Guidelines:
- Be precise with item names and quantities
- Only classify as 'order' if specific items and quantities are mentioned
- Return confidence between 0.0-1.0 based on clarity
- For ambiguous messages, use lower confidence

Examples:
"I want 2 iPhone 15 and 1 MacBook Pro" → order, confidence: 0.9
"What's the price of iPhone?" → enquiry, confidence: 0.8
"Great service, very happy!" → review, confidence: 0.9
"My address is 123 Main St" → address, confidence: 0.9
"Hello everyone" → general, confidence: 0.95"""

                user_content = f"Sender: {sender}\nMessage: {message_text}"
                if context:
                    user_content += f"\nContext: {context}"

                result = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    response_model=MessageClassification,
                    max_tokens=800,
                    temperature=0.1
                )

                # Validate the result
                if not isinstance(result.confidence, (int, float)) or not (0.0 <= result.confidence <= 1.0):
                    result.confidence = 0.5  # Default confidence

                return result

            except Exception as e:
                if self._is_rate_limit_error(e):
                    # Enhanced rate limit handling with exponential backoff
                    delay = self._calculate_backoff_delay(attempt)
                    print(f"Rate limit detected. Waiting {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(delay)
                else:
                    # Non-rate-limit errors
                    print(f"API Error on attempt {attempt + 1}/{self.max_retries}: {e}")
                    if attempt == self.max_retries - 1:
                        print(f"All attempts failed for message: {message_text[:50]}...")
                        return self._fallback_classification()
                    # Short delay for non-rate-limit errors
                    await asyncio.sleep(3)

        # If all retries exhausted due to rate limits
        print(f"Rate limit retries exhausted for message: {message_text[:50]}...")
        return self._fallback_classification()

    async def process_chat_messages(
        self,
        messages: List[Dict],
        chat_file_id: str,
        progress_callback=None
    ) -> Tuple[List[Dict], ProcessingStats]:
        """
        Process a list of chat messages and return classified results

        Args:
            messages: List of message dictionaries from chat parser
            chat_file_id: UUID string of the ChatFile
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (processed_messages, stats)
        """
        start_time = time.time()
        processed_messages = []
        message_types = {}
        orders_found = 0
        confidence_scores = {}
        successful_classifications = 0

        total_messages = len(messages)

        for i, message in enumerate(messages):
            try:
                # Extract message details
                message_text = message.get('Message', '')
                sender = message.get('Phone/Name', '')
                date = message.get('Date', '')
                time_str = message.get('Time', '')

                # Skip empty messages
                if not message_text.strip():
                    processed_message = message.copy()
                    processed_message.update({
                        'Message_Type': 'general',
                        'Confidence': 0.0,
                        'Order_Items': '',
                        'Order_Amount': '',
                        'Customer_Details': '',
                        'Notes': 'Empty message'
                    })
                    processed_messages.append(processed_message)
                    continue

                # Classify the message
                classification = await self.classify_message(
                    message_text=message_text,
                    sender=sender,
                    context=f"Date: {date} {time_str}"
                )

                # Create processed message matching sample format
                processed_message = message.copy()
                processed_message.update({
                    'Message_Type': classification.message_type.value,
                    'Items': '',  # Simple format: "Apples: 1, Pears: 1"
                    'Total_Amount': ''  # Simple format: "$74.0" or empty
                })

                # If it's an order, extract details in simple format
                if (classification.message_type == MessageType.ORDER and
                    classification.extracted_order):

                    order = classification.extracted_order

                    # Format items as simple string like sample: "Apples: 1, Pears: 1"
                    if order.items:
                        items_str = ', '.join([f"{item}: {qty}" for item, qty in order.items.items()])
                        processed_message['Items'] = items_str

                    # Format amount as simple string like sample: "$74.0"
                    if order.total_amount:
                        processed_message['Total_Amount'] = f"${order.total_amount}"

                    orders_found += 1

                processed_messages.append(processed_message)

                # Update statistics
                msg_type = classification.message_type.value
                message_types[msg_type] = message_types.get(msg_type, 0) + 1

                if msg_type not in confidence_scores:
                    confidence_scores[msg_type] = []
                confidence_scores[msg_type].append(classification.confidence)

                successful_classifications += 1

                # Progress callback
                if progress_callback:
                    progress = int((i + 1) / total_messages * 100)
                    await sync_to_async(progress_callback)(progress, i + 1, total_messages)

                # Rate limiting between messages
                if (i + 1) % self.batch_size == 0:
                    print(f"Processed batch {(i + 1) // self.batch_size}, waiting...")
                    await asyncio.sleep(2)  # Longer pause between batches

            except Exception as e:
                print(f"Error processing message {i}: {e}")
                # Add failed message with default classification
                processed_message = message.copy()
                processed_message.update({
                    'Message_Type': 'general',
                    'Confidence': 0.0,
                    'Order_Items': '',
                    'Order_Amount': '',
                    'Customer_Details': '',
                    'Notes': f'Processing error: {str(e)[:100]}'
                })
                processed_messages.append(processed_message)
                continue

        # Calculate statistics
        processing_time = time.time() - start_time
        success_rate = successful_classifications / total_messages if total_messages > 0 else 0

        # Calculate average confidence by type
        avg_confidence_scores = {}
        for msg_type, scores in confidence_scores.items():
            avg_confidence_scores[msg_type] = sum(scores) / len(scores) if scores else 0.0

        stats = ProcessingStats(
            total_messages=total_messages,
            message_types=message_types,
            orders_found=orders_found,
            confidence_scores=avg_confidence_scores,
            processing_time=processing_time,
            success_rate=success_rate
        )

        return processed_messages, stats

    @sync_to_async
    def _save_processed_file(self, processed_messages: List[Dict], output_path: str) -> bool:
        """Save processed messages to Excel file (sync function wrapped for async)"""
        return save_processed_chat_to_excel(processed_messages, output_path)

    @sync_to_async
    def _update_chat_file_status(self, chat_file_id: str, is_processed: bool, error: str = ""):
        """Update ChatFile processing status"""
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
    def _create_parsed_file_record(self, chat_file, processed_messages: List[Dict], stats: ProcessingStats, output_filename: str):
        """Create ParsedChatFile record"""
        parsed_file = ParsedChatFile.objects.create(
            user=chat_file.user,
            chatfile=chat_file,
            file_name=output_filename,
            processed_file_path=f"processedchatfile/{output_filename}",
            total_messages=stats.total_messages,
            total_orders=stats.orders_found,
            total_queries=stats.message_types.get('enquiry', 0)
        )
        return parsed_file


# Global service instance
django_ai_service = DjangoOrderExtractionService()