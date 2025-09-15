from django.db import models

# Create your models here.
# Simple Orders App Models with local file storage structure

from django.contrib.auth.models import User
from django.utils import timezone
import uuid
from .storage import OrdersFileStorage

class ChatFile(models.Model):
    """
    Stores uploaded WhatsApp chat files (.txt format)
    Files stored in: media/chatfile/
    """
    FILE_TYPES = [
        ('text', 'Text File (.txt)'),
        ('csv', 'CSV File (.csv)'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_chat_files')
    filename = models.CharField(max_length=255)
    filepath = models.FileField(upload_to='chatfile/', storage=OrdersFileStorage())
    filetype = models.CharField(max_length=10, choices=FILE_TYPES)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    # Processing status tracking
    is_processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True)
    
    class Meta:
        db_table = 'chat_files'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.filename} - {self.user.username}"

class ParsedChatFile(models.Model):
    """
    Stores processed chat files in XLSX format after AI processing
    Files stored in: media/processedchatfile/
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='processed_files')
    chatfile = models.OneToOneField(ChatFile, on_delete=models.CASCADE, related_name='processed_file')
    file_name = models.CharField(max_length=255)
    processed_file_path = models.FileField(upload_to='processedchatfile/', storage=OrdersFileStorage())
    processed_at = models.DateTimeField(auto_now_add=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    downloaded_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='downloaded_files'
    )
    
    # Statistics from processing
    total_messages = models.IntegerField(default=0)
    total_orders = models.IntegerField(default=0)
    total_queries = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'parsed_chat_files'
        ordering = ['-processed_at']
    
    def __str__(self):
        return f"Processed: {self.file_name}"

class ValidatedFile(models.Model):
    """
    Stores human-validated order files uploaded for message sending
    Files stored in: media/validatedchatfile/
    """
    FILE_TYPES = [
        ('xlsx', 'Excel File (.xlsx)'),
        ('csv', 'CSV File (.csv)'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='validated_files')
    file_name = models.CharField(max_length=255)
    filepath = models.FileField(upload_to='validatedchatfile/', storage=OrdersFileStorage())
    filetype = models.CharField(max_length=10, choices=FILE_TYPES)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # Link to original processing (optional)
    original_parsed_file = models.ForeignKey(
        ParsedChatFile, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='validated_versions'
    )
    
    # Processing status
    is_processed = models.BooleanField(default=False)
    orders_extracted = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'validated_files'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"Validated: {self.file_name}"

class Order(models.Model):
    """
    Individual customer orders extracted from validated files
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sent', 'Message Sent'),
        ('failed', 'Send Failed'),
        ('delivered', 'Message Delivered'),
        ('read', 'Message Read'),
    ]
    
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Payment Pending'),
        ('initiated', 'Payment Initiated'),
        ('completed', 'Payment Completed'),
        ('failed', 'Payment Failed'),
        ('cancelled', 'Payment Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    validated_file = models.ForeignKey(ValidatedFile, on_delete=models.CASCADE, related_name='orders')
    
    # Customer details
    order_id = models.CharField(max_length=20, unique=True, editable=False, help_text="Auto-generated order ID (format: 2025091500001)")
    number = models.CharField(max_length=20, help_text="Customer phone number")
    order_items = models.TextField(help_text="Order items: Apples:1,Pears:2")
    amount = models.TextField(help_text="Amount breakdown: 150+200=350")
    
    # WhatsApp Message Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # WhatsApp Message Tracking
    whatsapp_message_id = models.CharField(max_length=100, blank=True, help_text="WhatsApp message ID")
    whatsapp_response_code = models.IntegerField(null=True, blank=True, help_text="WhatsApp API response code")
    whatsapp_response_json = models.JSONField(default=dict, blank=True, help_text="Complete WhatsApp API response")

    # Payment Status & Tracking
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_reference_id = models.CharField(max_length=100, blank=True, null=True, help_text="Razorpay payment ID (pay_xyz)")
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True, help_text="Razorpay order ID (order_xyz)")
    payment_method = models.CharField(max_length=50, blank=True, help_text="Payment method: UPI, card, netbanking, etc.")
    payment_amount_captured = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Actual amount captured")

    # Payment Webhook Data
    payment_webhook_data = models.JSONField(default=dict, blank=True, help_text="Complete payment webhook payload")
    payment_captured_at = models.DateTimeField(null=True, blank=True, help_text="When payment was captured")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['number']),
            models.Index(fields=['status']),
            models.Index(fields=['payment_status']),
        ]
    
    def generate_order_id(self):
        """Generate date-based order ID: format YYYYMMDD00001"""
        today = timezone.now()
        date_prefix = today.strftime('%Y%m%d')  # 20250915

        # Count orders created today
        daily_count = Order.objects.filter(
            created_at__date=today.date()
        ).count() + 1

        return f"{date_prefix}{daily_count:05d}"  # 2025091500001

    def save(self, *args, **kwargs):
        """Auto-generate order_id if not set"""
        if not self.order_id:
            self.order_id = self.generate_order_id()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order {self.order_id} - {self.number} - {self.amount} - {self.status}"

class WebhookEvent(models.Model):
    """
    Stores incoming webhook events for message status and payment updates
    """
    EVENT_TYPES = [
        ('message_status', 'Message Status Update'),
        ('payment_status', 'Payment Status Update'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    message_id = models.CharField(max_length=100, blank=True)
    payment_reference_id = models.CharField(max_length=100, blank=True)
    
    # Raw webhook data
    raw_data = models.JSONField()
    
    # Processing status
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)
    
    # Associated order (if found)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_events')
    
    received_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'webhook_events'
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['message_id']),
            models.Index(fields=['payment_reference_id']),
        ]