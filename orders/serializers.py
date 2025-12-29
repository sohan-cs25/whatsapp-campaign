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
            'id', 'chatfile_filename', 'file_name', 'processed_at',
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

    validated_file_name = serializers.CharField(source='validated_file.file_name', read_only=True)

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
            'id', 'validated_file_name', 'sent_at', 'message_id', 'response_code',
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