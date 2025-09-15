from django.contrib import admin
from django.utils.html import format_html
from .models import ChatFile, ParsedChatFile, ValidatedFile, Order, WebhookEvent


@admin.register(ChatFile)
class ChatFileAdmin(admin.ModelAdmin):
    list_display = ['filename', 'user', 'filetype', 'uploaded_at', 'is_processed', 'processed_at']
    list_filter = ['filetype', 'is_processed', 'uploaded_at']
    search_fields = ['filename', 'user__username']
    readonly_fields = ['id', 'uploaded_at', 'processed_at']
    ordering = ['-uploaded_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(ParsedChatFile)
class ParsedChatFileAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'user', 'total_messages', 'total_orders', 'total_queries', 'processed_at']
    list_filter = ['processed_at']
    search_fields = ['file_name', 'user__username']
    readonly_fields = ['id', 'processed_at', 'downloaded_at']
    ordering = ['-processed_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'chatfile')


@admin.register(ValidatedFile)
class ValidatedFileAdmin(admin.ModelAdmin):
    list_display = ['file_name', 'user', 'filetype', 'orders_extracted', 'uploaded_at', 'is_processed']
    list_filter = ['filetype', 'is_processed', 'uploaded_at']
    search_fields = ['file_name', 'user__username']
    readonly_fields = ['id', 'uploaded_at']
    ordering = ['-uploaded_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'number', 'status', 'payment_status', 'payment_amount_captured', 'created_at']
    list_filter = ['status', 'payment_status', 'payment_method', 'created_at']
    search_fields = ['order_id', 'number', 'whatsapp_message_id', 'payment_reference_id']
    readonly_fields = ['id', 'order_id', 'created_at', 'updated_at', 'sent_at', 'delivered_at', 'read_at', 'payment_captured_at']
    ordering = ['-created_at']

    fieldsets = (
        ('Order Information', {
            'fields': ('order_id', 'validated_file', 'number', 'order_items', 'amount')
        }),
        ('Message Status', {
            'fields': ('status', 'sent_at', 'delivered_at', 'read_at', 'whatsapp_message_id', 'whatsapp_response_code')
        }),
        ('Payment Information', {
            'fields': ('payment_status', 'payment_method', 'payment_amount_captured', 'payment_reference_id', 'razorpay_order_id', 'payment_captured_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Technical Data', {
            'fields': ('whatsapp_response_json', 'payment_webhook_data'),
            'classes': ('collapse',)
        })
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('validated_file', 'validated_file__user')

    def colored_status(self, obj):
        colors = {
            'pending': 'orange',
            'sent': 'blue',
            'delivered': 'green',
            'read': 'darkgreen',
            'failed': 'red'
        }
        color = colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.get_status_display()
        )
    colored_status.short_description = 'Status'

    def colored_payment_status(self, obj):
        colors = {
            'pending': 'orange',
            'initiated': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray'
        }
        color = colors.get(obj.payment_status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.get_payment_status_display()
        )
    colored_payment_status.short_description = 'Payment Status'


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'message_id', 'payment_reference_id', 'processed', 'received_at']
    list_filter = ['event_type', 'processed', 'received_at']
    search_fields = ['message_id', 'payment_reference_id']
    readonly_fields = ['id', 'received_at', 'processed_at']
    ordering = ['-received_at']

    fieldsets = (
        ('Event Information', {
            'fields': ('event_type', 'message_id', 'payment_reference_id', 'order')
        }),
        ('Processing Status', {
            'fields': ('processed', 'processed_at', 'processing_error')
        }),
        ('Raw Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('received_at',)
        })
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('order')
