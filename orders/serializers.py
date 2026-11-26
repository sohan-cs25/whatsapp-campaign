from rest_framework import serializers
from django.contrib.auth.models import User
from .models import ChatFile, ParsedChatFile, ValidatedFile, Order, WebhookEvent


class ChatFileSerializer(serializers.ModelSerializer):
    """Serializer for ChatFile model - handles .txt file uploads"""

    class Meta:
        model = ChatFile
        fields = [
            'id', 'user', 'filename', 'filepath', 'filetype',
            'uploaded_at', 'processed_at', 'is_processed', 'processing_error'
        ]
        read_only_fields = ['id', 'user', 'uploaded_at', 'processed_at', 'is_processed', 'processing_error']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ChatFileListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing chat files"""

    class Meta:
        model = ChatFile
        fields = ['id', 'filename', 'filetype', 'uploaded_at', 'is_processed']


class ParsedChatFileSerializer(serializers.ModelSerializer):
    """Serializer for ParsedChatFile model - AI processed files"""

    chatfile_info = serializers.SerializerMethodField()

    class Meta:
        model = ParsedChatFile
        fields = [
            'id', 'user', 'chatfile', 'chatfile_info', 'file_name',
            'processed_file_path', 'processed_at', 'downloaded_at', 'downloaded_by',
            'total_messages', 'total_orders', 'total_queries'
        ]
        read_only_fields = [
            'id', 'user', 'processed_at', 'downloaded_at', 'downloaded_by',
            'total_messages', 'total_orders', 'total_queries'
        ]

    def get_chatfile_info(self, obj):
        return {
            'filename': obj.chatfile.filename,
            'uploaded_at': obj.chatfile.uploaded_at
        }


class ParsedChatFileListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing processed files"""

    chatfile_filename = serializers.CharField(source='chatfile.filename', read_only=True)

    class Meta:
        model = ParsedChatFile
        fields = [
            'id', 'chatfile', 'chatfile_filename', 'file_name', 'processed_at',
            'total_messages', 'total_orders', 'total_queries', 'downloaded_at'
        ]


class ValidatedFileSerializer(serializers.ModelSerializer):
    """Serializer for ValidatedFile model - human-validated orders"""

    original_parsed_info = serializers.SerializerMethodField()

    class Meta:
        model = ValidatedFile
        fields = [
            'id', 'user', 'file_name', 'filepath', 'filetype', 'uploaded_at',
            'original_parsed_file', 'original_parsed_info', 'is_processed', 'orders_extracted'
        ]
        read_only_fields = ['id', 'user', 'uploaded_at', 'is_processed', 'orders_extracted']

    def get_original_parsed_info(self, obj):
        if obj.original_parsed_file:
            return {
                'id': obj.original_parsed_file.id,
                'filename': obj.original_parsed_file.file_name,
                'processed_at': obj.original_parsed_file.processed_at
            }
        return None

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ValidatedFileListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing validated files"""

    class Meta:
        model = ValidatedFile
        fields = ['id', 'file_name', 'filetype', 'uploaded_at', 'is_processed', 'orders_extracted']


class OrderSerializer(serializers.ModelSerializer):
    """Serializer for Order model"""

    validated_file_name = serializers.CharField(source='validated_file.file_name', read_only=True, default=None)

    class Meta:
        model = Order
        fields = [
            'id', 'validated_file', 'validated_file_name', 'number', 'order_items', 'amount',
            'status', 'sent_at', 'message_id', 'response_code', 'response_json',
            'payment_status', 'delivered_at', 'read_at', 'payment_reference_id',
            'payment_success_message_sent', 'payment_success_message_id',
            'payment_success_sent_at', 'payment_success_message_status',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'validated_file', 'validated_file_name', 'sent_at', 'message_id', 'response_code',
            'response_json', 'delivered_at', 'read_at', 'payment_success_message_sent',
            'payment_success_message_id', 'payment_success_sent_at', 'payment_success_message_status',
            'created_at', 'updated_at'
        ]


class OrderListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing orders"""

    class Meta:
        model = Order
        fields = [
            'id', 'number', 'amount', 'status', 'payment_status',
            'payment_success_message_sent', 'payment_success_message_status',
            'created_at', 'sent_at'
        ]


class WebhookEventSerializer(serializers.ModelSerializer):
    """Serializer for WebhookEvent model"""

    class Meta:
        model = WebhookEvent
        fields = [
            'id', 'event_type', 'message_id', 'payment_reference_id',
            'raw_data', 'processed', 'processed_at', 'processing_error',
            'order', 'received_at'
        ]
        read_only_fields = ['id', 'processed_at', 'received_at']


class FileUploadProgressSerializer(serializers.Serializer):
    """Serializer for file upload progress responses"""

    status = serializers.CharField()
    message = serializers.CharField()
    progress = serializers.IntegerField(min_value=0, max_value=100)
    file_id = serializers.UUIDField(required=False)
    data = serializers.JSONField(required=False)


class ProcessingStatsSerializer(serializers.Serializer):
    """Serializer for processing statistics"""

    total_files_uploaded = serializers.IntegerField()
    total_files_processed = serializers.IntegerField()
    total_files_validated = serializers.IntegerField()
    total_orders_extracted = serializers.IntegerField()
    total_messages_sent = serializers.IntegerField()
    processing_success_rate = serializers.FloatField()

# ── Review flow ─────────────────────────────────────────────────────────────

from .models import CustomerContact, OrderLine, Product, UNITS, flat_key, normalize_phone  # noqa: E402


class OrderLineSerializer(serializers.ModelSerializer):
    product = serializers.SlugRelatedField(slug_field='key', read_only=True)

    class Meta:
        model = OrderLine
        fields = ['id', 'product', 'name', 'quantity', 'unit', 'unit_price_paise', 'line_total_paise',
                  'as_written', 'flags']


class ReviewOrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True, read_only=True)
    blocking_issues = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ['id', 'order_id', 'customer_name', 'number', 'address', 'review_status', 'needs_review',
                  'review_flags', 'blocking_issues', 'total_paise', 'status', 'payment_status', 'lines',
                  'messages']

    messages = serializers.SerializerMethodField()

    def get_blocking_issues(self, obj):
        return obj.blocking_issues()

    def get_messages(self, obj):
        """The customer's chat messages; 'used' marks the ones the order lines came from.
        Pass context['messages_by_sender'] to avoid a query per order."""
        by_sender = self.context.get('messages_by_sender')
        if by_sender is None:
            from .models import ChatMessage
            msgs = list(ChatMessage.objects.filter(parsed_file_id=obj.parsed_file_id, sender=obj.chat_sender)
                        ) if obj.parsed_file_id and obj.chat_sender else []
        else:
            msgs = by_sender.get(obj.chat_sender, [])
        used = {m for line in obj.lines.all() for m in (line.message_ids or '').split(',') if m}
        return [chat_message_data(m, used=bool(m.msg_id) and m.msg_id in used) for m in msgs]


def chat_message_data(m, **extra):
    return {'id': m.msg_id, 'date': m.date, 'time': m.time, 'sender': m.sender, 'text': m.text, **extra}


class LineInputSerializer(serializers.Serializer):
    product = serializers.CharField(allow_null=True, required=False)
    name = serializers.CharField(max_length=120)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3, allow_null=True, required=False)

    def validate_quantity(self, q):
        if q is not None and q <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0; remove the line instead")
        return q
    unit = serializers.ChoiceField(choices=UNITS + [''], allow_blank=True, required=False, default='')

    def validate_product(self, key):
        if key in (None, ''):
            return None
        try:
            return Product.objects.get(key=key)
        except Product.DoesNotExist:
            raise serializers.ValidationError(f"Unknown product '{key}'")


class ReviewOrderUpdateSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=20, allow_blank=True, required=False)
    address = serializers.CharField(max_length=64, allow_blank=True, required=False)
    customer_name = serializers.CharField(max_length=120, allow_blank=True, required=False)
    review_status = serializers.ChoiceField(choices=['draft', 'rejected'], required=False)
    lines = LineInputSerializer(many=True, required=False)


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'key', 'name', 'price', 'price_unit', 'is_active', 'updated_at']
        read_only_fields = ['id', 'updated_at']


class CustomerContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerContact
        fields = ['id', 'flat', 'flat_key', 'phone', 'name', 'updated_at']
        read_only_fields = ['id', 'flat_key', 'updated_at']
        validators = []  # (user, flat_key) uniqueness is handled as an upsert in the view

    def validate_flat(self, value):
        if not flat_key(value):
            raise serializers.ValidationError("Needs a flat/house number, e.g. C-234 or 182")
        return value.strip()

    def validate_phone(self, value):
        phone = normalize_phone(value)
        if not phone:
            raise serializers.ValidationError("Not a phone number; use 10 digits or 91 followed by 10 digits")
        return phone
