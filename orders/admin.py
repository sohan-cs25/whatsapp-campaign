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
    list_display = ['order_id', 'number', 'colored_status', 'colored_payment_status', 'payment_success_message_sent', 'payment_amount_captured', 'created_at']
    list_filter = ['status', 'payment_status', 'payment_method', 'payment_success_message_sent', 'payment_success_message_status', 'created_at']
    search_fields = ['order_id', 'number', 'whatsapp_message_id', 'payment_reference_id', 'payment_success_message_id']
    readonly_fields = ['id', 'order_id', 'created_at', 'updated_at', 'sent_at', 'delivered_at', 'read_at', 'payment_captured_at', 'payment_success_sent_at']
    ordering = ['-created_at']
    actions = ['resend_payment_success_message']

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
        ('Payment Success Message', {
            'fields': ('payment_success_message_sent', 'payment_success_message_status', 'payment_success_message_id', 'payment_success_sent_at'),
            'description': 'Automatic payment success notification sent to customer'
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

    def payment_success_message_status_display(self, obj):
        """Display payment success message status with colors"""
        if not obj.payment_success_message_sent:
            return format_html('<span style="color: gray;">Not Sent</span>')

        colors = {
            'sent': 'blue',
            'delivered': 'green',
            'read': 'darkgreen',
            'failed': 'red'
        }
        color = colors.get(obj.payment_success_message_status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.payment_success_message_status.title()
        )
    payment_success_message_status_display.short_description = 'Payment Message Status'

    def resend_payment_success_message(self, request, queryset):
        """Admin action to resend payment success messages for selected orders"""
        from .whatsapp_service import OrderWhatsAppService
        from django.contrib import messages

        success_count = 0
        error_count = 0

        for order in queryset:
            # Only resend for completed payments
            if order.payment_status != 'completed':
                error_count += 1
                continue

            try:
                whatsapp_service = OrderWhatsAppService()

                # Create payment data from stored webhook data
                payment_data = order.payment_webhook_data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {}).get('statuses', [{}])[0].get('payment', {})

                if not payment_data:
                    # Fallback payment data from order fields
                    payment_data = {
                        'reference_id': order.order_id,
                        'amount': {
                            'value': int(order.payment_amount_captured * 100) if order.payment_amount_captured else 0,
                            'offset': 100
                        },
                        'transaction': {
                            'pg_transaction_id': order.payment_reference_id or 'manual_resend',
                            'method': {
                                'type': order.payment_method or 'unknown'
                            }
                        }
                    }

                response = whatsapp_service.send_payment_success_message(order, payment_data)

                if response and response.get('success', False):
                    success_count += 1
                else:
                    error_count += 1

            except Exception as e:
                error_count += 1

        if success_count > 0:
            messages.success(request, f'Successfully resent {success_count} payment success messages.')
        if error_count > 0:
            messages.error(request, f'Failed to resend {error_count} payment success messages.')

    resend_payment_success_message.short_description = "Resend payment success messages"


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
