"""
Enhanced Order Extractor Service
Handles LLM-powered order extraction with rate limiting and error handling
"""

import asyncio
import os
import time
import json
import random
from typing import List, Dict, Optional
from datetime import datetime
import instructor
from groq import Groq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from dotenv import load_dotenv

from models import ChatMessage, ExtractedOrder, MessageType, ChatFile, ProcessingStatus
from schemas import MessageClassification, OrderDetails

# Load environment variables
load_dotenv()

class OrderExtractionService:
    """Service for extracting orders from chat messages using Groq LLM"""
    
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        # Initialize Groq client with instructor
        groq_client = Groq(api_key=self.api_key)
        self.client = instructor.from_groq(groq_client, mode=instructor.Mode.JSON)
        
        # Enhanced rate limiting configuration
        self.base_delay = 1.0  # Base delay between requests
        self.max_delay = 60.0  # Maximum delay cap
        self.max_retries = 5  # Increased retries for rate limits
        self.jitter_range = 0.1  # Random jitter factor
        self.queue = asyncio.Queue()
        self.processing = False
    
    def _is_rate_limit_error(self, error) -> bool:
        """Check if error is related to rate limiting"""
        error_str = str(error).lower()
        rate_limit_indicators = [
            "rate limit", "too many requests", "quota exceeded", 
            "429", "rate_limit_exceeded", "requests per minute"
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
        
        # Ensure minimum delay of 0.1 seconds
        final_delay = max(0.1, capped_delay + jitter)
        
        return final_delay
    
    def _fallback_classification(self) -> MessageClassification:
        """Return fallback classification when all retries fail"""
        return MessageClassification(
            message_type="general",
            confidence=0.0,
            extracted_order=None
        )

    async def classify_message(self, message_text: str) -> MessageClassification:
        """Classify a single message using Groq LLM with enhanced rate limit handling"""
        for attempt in range(self.max_retries):
            try:
                # Add base delay to respect rate limits
                await asyncio.sleep(self.base_delay)
                
                result = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {
                            "role": "system", 
                            "content": """You are a WhatsApp group chat analyzer for an order processing system.
                            
                            Classify each message into one of these categories:
                            - order: Customer placing an order for products
                            - review: Customer feedback or reviews  
                            - enquiry: Questions about products, prices, availability
                            - address: Delivery address information
                            - announcement: Business announcements or updates
                            - general: General conversation, greetings, etc.
                            
                            If the message is an ORDER, extract:
                            - items: Dictionary of product names and quantities (e.g., {"iPhone 15": 2, "MacBook Pro": 1})
                            
                            Be precise with item names and quantities. Return confidence as a float between 0.0 and 1.0.
                            
                            example:
                            message: "1 box apples 1 box pears"
                            response: {message_type='order' confidence=0.9 extracted_order=OrderDetails(items={'apples': 1, 'pears': 1}) }

                            message: "1 box apple 1box pears #369 phase2"
                            response: {message_type='order' confidence=0.9 extracted_order=OrderDetails(items={'apple': 1, 'pears': 1}) }
                            """
                        },
                        {"role": "user", "content": message_text}
                    ],
                    response_model=MessageClassification,
                    max_tokens=500,
                    temperature=0.1
                )
                return result
                
            except Exception as e:
                if self._is_rate_limit_error(e):
                    # Enhanced rate limit handling with exponential backoff
                    delay = self._calculate_backoff_delay(attempt)
                    print(f"Rate limit detected. Waiting {delay:.2f}s (attempt {attempt + 1}/{self.max_retries})")
                    print(f"Error details: {e}")
                    await asyncio.sleep(delay)
                else:
                    # Non-rate-limit errors
                    print(f"API Error on attempt {attempt + 1}/{self.max_retries}: {e}")
                    if attempt == self.max_retries - 1:
                        print(f"All attempts failed for message: {message_text[:50]}...")
                        return self._fallback_classification()
                    # Short delay for non-rate-limit errors
                    await asyncio.sleep(2)
        
        # If all retries exhausted due to rate limits
        print(f"Rate limit retries exhausted for message: {message_text[:50]}...")
        return self._fallback_classification()
    
    async def process_chat_file(
        self, 
        chat_file_id: int, 
        session: AsyncSession
    ) -> Dict[str, any]:
        """Process all messages in a chat file"""
        start_time = time.time()
        
        try:
            # Update processing status
            await session.execute(
                update(ChatFile)
                .where(ChatFile.id == chat_file_id)
                .values(processing_status=ProcessingStatus.IN_PROGRESS)
            )
            await session.commit()
            
            # Get all messages for this chat file
            stmt = select(ChatMessage).where(ChatMessage.chat_file_id == chat_file_id)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            
            if not messages:
                raise ValueError(f"No messages found for chat_file_id {chat_file_id}")
            
            processed_count = 0
            orders_found = 0
            
            for message in messages:
                try:
                    # Classify the message
                    classification = await self.classify_message(message.message)
                    
                    # Update message with classification
                    message.message_type = MessageType(classification.message_type)
                    message.classification_confidence = classification.confidence
                    message.processed_at = datetime.utcnow()
                    
                    # If it's an order, save the extracted details
                    if (classification.message_type == "order" and 
                        classification.extracted_order):
                        
                        extracted_order = ExtractedOrder(
                            message_id=message.id,
                            customer_name=classification.extracted_order.customer_name,
                            items_json=classification.extracted_order.to_json_string(),
                            total_amount=classification.extracted_order.total_amount,
                            delivery_address=classification.extracted_order.delivery_address,
                            extracted_at=datetime.utcnow()
                        )
                        
                        session.add(extracted_order)
                        orders_found += 1
                    
                    processed_count += 1
                    
                    # Commit in batches to avoid long transactions
                    if processed_count % 10 == 0:
                        await session.commit()
                        print(f"Processed {processed_count}/{len(messages)} messages...")
                
                except Exception as e:
                    print(f"Error processing message {message.id}: {e}")
                    continue
            
            # Final commit
            await session.commit()
            
            # Update processing status to completed
            await session.execute(
                update(ChatFile)
                .where(ChatFile.id == chat_file_id)
                .values(processing_status=ProcessingStatus.COMPLETED)
            )
            await session.commit()
            
            processing_time = time.time() - start_time
            
            return {
                "status": "completed",
                "chat_file_id": chat_file_id,
                "total_messages": len(messages),
                "processed_messages": processed_count,
                "orders_found": orders_found,
                "processing_time": processing_time
            }
            
        except Exception as e:
            # Update processing status to failed
            await session.execute(
                update(ChatFile)
                .where(ChatFile.id == chat_file_id)
                .values(processing_status=ProcessingStatus.FAILED)
            )
            await session.commit()
            
            return {
                "status": "failed",
                "chat_file_id": chat_file_id,
                "error": str(e),
                "processing_time": time.time() - start_time
            }
    
    async def get_extracted_orders(
        self, 
        chat_file_id: int, 
        session: AsyncSession
    ) -> List[Dict]:
        """Get all extracted orders for a chat file"""
        stmt = (
            select(ExtractedOrder, ChatMessage)
            .join(ChatMessage)
            .where(ChatMessage.chat_file_id == chat_file_id)
        )
        
        result = await session.execute(stmt)
        orders = result.all()
        
        extracted_orders = []
        for order, message in orders:
            # Parse items from JSON
            items = json.loads(order.items_json)
            
            extracted_orders.append({
                "id": order.id,
                "message_id": order.message_id,
                "customer_name": order.customer_name,
                "items": items,
                "total_amount": order.total_amount,
                "delivery_address": order.delivery_address,
                "extracted_at": order.extracted_at,
                "original_message": message.message,
                "sender": message.sender,
                "date": message.date,
                "time": message.time
            })
        
        return extracted_orders

# Global service instance
order_service = OrderExtractionService()