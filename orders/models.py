from django.db import models
from django.db.models import Q

# Create your models here.
# Simple Orders App Models with local file storage structure

from django.contrib.auth.models import User
from django.utils import timezone
from django.db import IntegrityError, transaction
import re
import uuid
from .storage import OrdersFileStorage

from .order_extractor import UNITS

UNIT_CHOICES = [(u, u) for u in UNITS]


class Product(models.Model):
    """Products on sale and their prices: the single source of truth for pricing."""
    key = models.SlugField(max_length=64, unique=True, help_text="snake_case id the AI maps items to")
    name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price in rupees per price_unit")
    price_unit = models.CharField(max_length=10, choices=UNIT_CHOICES)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} (₹{self.price}/{self.price_unit})"

    @classmethod
    def as_catalog(cls):
        """Active products in the catalog format order_extractor expects."""
        return [
            {"id": p.key, "name": p.name, "price": float(p.price), "price_per": p.price_unit,
             "first_announced_id": "", "notes": None}
            for p in cls.objects.filter(is_active=True)
        ]


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

class OrderQuerySet(models.QuerySet):
    def for_user(self, user):
        """Orders owned by user. Falls back to the validated file's owner for orders that
        predate Order.user (so a migration without the backfill does not hide them)."""
        return self.filter(Q(user=user) | Q(user__isnull=True, validated_file__user=user))


class Order(models.Model):
    """
    Individual customer orders extracted from validated files
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('sending', 'Sending'),
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
    
    REVIEW_STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', null=True)
    validated_file = models.ForeignKey(ValidatedFile, on_delete=models.CASCADE, related_name='orders',
                                       null=True, blank=True)
    parsed_file = models.ForeignKey(ParsedChatFile, on_delete=models.SET_NULL, related_name='orders',
                                    null=True, blank=True)

    # Review
    customer_name = models.CharField(max_length=120, blank=True)
    chat_sender = models.CharField(max_length=120, blank=True,
                                   help_text="Sender name/number exactly as in the chat; links the order to its messages")
    address = models.CharField(max_length=64, blank=True)
    review_status = models.CharField(max_length=10, choices=REVIEW_STATUS_CHOICES, default='draft')
    needs_review = models.BooleanField(default=False)
    review_flags = models.JSONField(default=list, blank=True)
    total_paise = models.PositiveIntegerField(null=True, blank=True)
    
    # Customer details
    order_id = models.CharField(max_length=20, unique=True, editable=False, help_text="Auto-generated order ID (format: 2025091500001)")
    number = models.CharField(max_length=20, blank=True, help_text="Customer phone number")
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

    # Payment Success Message Tracking
    payment_success_message_sent = models.BooleanField(default=False, help_text="Whether payment success message was sent")
    payment_success_message_id = models.CharField(max_length=100, blank=True, help_text="WhatsApp message ID for payment success notification")
    payment_success_sent_at = models.DateTimeField(null=True, blank=True, help_text="When payment success message was sent")
    payment_success_message_status = models.CharField(max_length=20, blank=True, help_text="Status of payment success message (sent, delivered, read, failed)")

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
    
    objects = OrderQuerySet.as_manager()

    def generate_order_id(self):
        """Date-based order ID YYYYMMDDnnnnn: today's highest suffix + 1 (safe after deletions)."""
        date_prefix = timezone.now().strftime('%Y%m%d')
        last = (Order.objects.filter(order_id__startswith=date_prefix)
                .order_by('-order_id').values_list('order_id', flat=True).first())
        next_n = int(last[len(date_prefix):]) + 1 if last else 1
        return f"{date_prefix}{next_n:05d}"

    def save(self, *args, **kwargs):
        """Auto-generate order_id if not set; retry on a concurrent collision."""
        if self.order_id:
            return super().save(*args, **kwargs)
        for attempt in range(5):
            self.order_id = self.generate_order_id()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.order_id = ''
                if attempt == 4:
                    raise
                kwargs.pop('force_insert', None)

    def refresh_totals(self):
        """Recompute total_paise from lines and refill the legacy order_items/amount strings."""
        lines = list(self.lines.all())
        self.total_paise = sum(l.line_total_paise for l in lines)
        self.order_items = ", ".join(
            f"{l.name}: {_fmt_qty(l.quantity)} {l.unit}".strip() if l.quantity is not None else l.name
            for l in lines)
        self.amount = ("+".join(_rupees(l.line_total_paise) for l in lines) + "=" + _rupees(self.total_paise)
                       if lines else "")
        self.save()

    def blocking_issues(self):
        """Reasons this order cannot be approved, in a fixed order."""
        issues = []
        lines = list(self.lines.all())
        if not re.fullmatch(r"\d{10,15}", self.number or ""):
            issues.append("no_phone")
        if not lines:
            issues.append("no_lines")
        if not self.total_paise:
            issues.append("zero_total")
        if any(l.line_total_paise == 0 for l in lines):
            issues.append("unpriced_line")
        return issues

    def __str__(self):
        return f"Order {self.order_id} - {self.number} - {self.amount} - {self.status}"

def _fmt_qty(q):
    return format(q.normalize(), 'f') if q is not None else ""


def _rupees(paise):
    paise = paise or 0
    return str(paise // 100) if paise % 100 == 0 else f"{paise / 100:.2f}"


PRICING_FLAGS = {"unknown_product", "unit_mismatch", "missing_quantity"}


class OrderLine(models.Model):
    """One priced item of an Order."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=120)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=10, blank=True)
    unit_price_paise = models.PositiveIntegerField(default=0)
    line_total_paise = models.PositiveIntegerField(default=0)
    as_written = models.TextField(blank=True)
    message_ids = models.CharField(max_length=255, blank=True)
    flags = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'order_lines'
        ordering = ['id']

    def __str__(self):
        return f"{self.name} {self.quantity} {self.unit}"

    def reprice(self):
        """Set price fields and pricing flags from the product; keeps non-pricing flags. Does not save."""
        from .pricing import price_line
        priced = price_line(self.product, self.quantity, self.unit or None)
        self.unit_price_paise = priced.unit_price_paise
        self.line_total_paise = priced.line_total_paise
        self.flags = [f for f in (self.flags or []) if f not in PRICING_FLAGS] + priced.flags


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

# ── Customer directory and chat messages ────────────────────────────────────

def flat_key(address) -> str:
    """Comparable key for a flat/house: block letter + number. 'C-234', '234-c' and '234 C'
    all give 'C234'; 'House 182' and '182-Jalvayu' give '182'. Words (House, JVV, a building
    name) are ignored; no number gives ''."""
    tokens = re.findall(r"[A-Z]+|\d+", str(address or "").upper())
    number = next((t for t in tokens if t.isdigit()), "")
    if not number:
        return ""
    letter = next((t for t in tokens if t.isalpha() and len(t) == 1), "")
    return f"{letter}{number}"


def normalize_phone(raw) -> str:
    """Digits only, with 91 added to a 10-digit Indian number; '' if it is not a phone number."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10:
        digits = "91" + digits
    return digits if 10 <= len(digits) <= 15 else ""


class CustomerContact(models.Model):
    """A seller's flat -> phone directory. Fills in phone numbers for orders whose chat
    shows only a saved contact name; reviewers' phone edits are remembered here."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_contacts')
    flat = models.CharField(max_length=32, help_text="As written, e.g. C-234")
    flat_key = models.CharField(max_length=32, editable=False)
    phone = models.CharField(max_length=20)
    name = models.CharField(max_length=120, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_contacts'
        ordering = ['flat_key']
        constraints = [models.UniqueConstraint(fields=['user', 'flat_key'], name='uniq_contact_flat_per_user')]

    def __str__(self):
        return f"{self.flat} -> {self.phone}"

    def save(self, *args, **kwargs):
        self.flat_key = flat_key(self.flat)
        self.phone = normalize_phone(self.phone) or self.phone
        super().save(*args, **kwargs)

    @classmethod
    def phone_for(cls, user, address) -> str:
        key = flat_key(address)
        if not key or user is None:
            return ""
        return cls.objects.filter(user=user, flat_key=key).values_list('phone', flat=True).first() or ""

    @classmethod
    def remember(cls, user, address, phone, name=""):
        """Save (or update) the phone for this flat. Ignores unusable flats or numbers."""
        key, phone = flat_key(address), normalize_phone(phone)
        if not key or not phone or user is None:
            return None
        contact, _ = cls.objects.update_or_create(
            user=user, flat_key=key, defaults={'flat': address, 'phone': phone, **({'name': name} if name else {})})
        return contact


class ChatMessage(models.Model):
    """Every message of a processed chat, kept so reviewers can see where an order came from.
    msg_id is the extractor's id (m0, m1, ...) and '' for skipped rows (media, deleted)."""
    parsed_file = models.ForeignKey(ParsedChatFile, on_delete=models.CASCADE, related_name='messages')
    position = models.PositiveIntegerField()
    msg_id = models.CharField(max_length=16, blank=True)
    date = models.CharField(max_length=20, blank=True)
    time = models.CharField(max_length=20, blank=True)
    sender = models.CharField(max_length=120)
    text = models.TextField(blank=True)
    is_seller = models.BooleanField(default=False)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['parsed_file', 'position']
        indexes = [models.Index(fields=['parsed_file', 'sender'])]

    def __str__(self):
        return f"[{self.msg_id}] {self.sender}: {self.text[:40]}"
