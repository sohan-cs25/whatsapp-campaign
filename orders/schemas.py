"""
Pydantic schemas for AI message classification and order extraction
Adapted for Django orders app
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum


class MessageType(str, Enum):
    """Message classification types"""
    ORDER = "order"
    ENQUIRY = "enquiry"
    REVIEW = "review"
    ADDRESS = "address"
    ANNOUNCEMENT = "announcement"
    GENERAL = "general"


class OrderDetails(BaseModel):
    """Structured order details extracted from messages"""

    items: Dict[str, int] = Field(
        description="Dictionary of product names and quantities"
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="Customer name if mentioned"
    )
    total_amount: Optional[float] = Field(
        default=None,
        description="Total order amount if mentioned"
    )
    delivery_address: Optional[str] = Field(
        default=None,
        description="Delivery address if provided"
    )
    phone_number: Optional[str] = Field(
        default=None,
        description="Customer phone number if different from sender"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional order notes or special instructions"
    )

    def to_json_string(self) -> str:
        """Convert order details to JSON string for database storage"""
        return self.model_dump_json()

    @classmethod
    def from_json_string(cls, json_str: str) -> "OrderDetails":
        """Create OrderDetails from JSON string"""
        import json
        return cls(**json.loads(json_str))


class MessageClassification(BaseModel):
    """AI classification result for a message"""

    message_type: MessageType = Field(
        description="Classification of the message type"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0"
    )
    extracted_order: Optional[OrderDetails] = Field(
        default=None,
        description="Extracted order details if message is an order"
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="AI reasoning for the classification"
    )

    class Config:
        json_encoders = {
            MessageType: lambda v: v.value
        }


class BatchClassificationRequest(BaseModel):
    """Request model for batch message classification"""

    messages: list[Dict[str, Any]] = Field(
        description="List of message dictionaries to classify"
    )
    chat_file_id: str = Field(
        description="UUID of the chat file being processed"
    )


class BatchClassificationResponse(BaseModel):
    """Response model for batch message classification"""

    chat_file_id: str
    total_messages: int
    processed_messages: int
    classifications: list[MessageClassification]
    orders_found: int
    processing_time: float
    status: str = Field(default="completed")
    error: Optional[str] = Field(default=None)


class ProcessingStats(BaseModel):
    """Processing statistics for a chat file"""

    total_messages: int
    message_types: Dict[str, int]  # Count by message type
    orders_found: int
    confidence_scores: Dict[str, float]  # Average confidence by type
    processing_time: float
    success_rate: float