from django.contrib import admin

# Register your models here.

# campaigns/admin.py

from .models import Campaign, UploadedFile, Message, WebhookLog


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'template_name', 'status', 'total_recipients', 
                    'sent_count', 'delivered_count', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['template_name', 'user__username']
    readonly_fields = ['created_at', 'started_at', 'completed_at']
    
    fieldsets = (
        ('Campaign Info', {
            'fields': ('user', 'template_name', 'status')
        }),
        ('Statistics', {
            'fields': ('total_recipients', 'sent_count', 'delivered_count', 
                      'read_count', 'failed_count')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'started_at', 'completed_at')
        }),
    )


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ['id', 'file_name', 'campaign', 'status', 'row_count', 
                    'valid_rows', 'invalid_rows', 'uploaded_at']
    list_filter = ['status', 'file_type', 'uploaded_at']
    search_fields = ['file_name', 'campaign__template_name']
    readonly_fields = ['uploaded_at', 'processed_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'campaign', 'phone_number', 'status', 'sent_at', 
                    'delivered_at', 'retry_count']
    list_filter = ['status', 'has_variables', 'has_media', 'sent_at']
    search_fields = ['phone_number', 'message_id', 'whatsapp_id']
    readonly_fields = ['sent_at', 'delivered_at', 'read_at', 'failed_at']
    
    fieldsets = (
        ('Message Info', {
            'fields': ('campaign', 'phone_number', 'whatsapp_id', 'message_id')
        }),
        ('Content', {
            'fields': ('has_variables', 'variables', 'has_media', 'media_url')
        }),
        ('Status', {
            'fields': ('status', 'retry_count', 'error_message')
        }),
        ('Response', {
            'fields': ('response_code', 'response_json')
        }),
        ('Timestamps', {
            'fields': ('sent_at', 'delivered_at', 'read_at', 'failed_at')
        }),
    )


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'event_type', 'processed', 'message_id', 'created_at']
    list_filter = ['event_type', 'processed', 'created_at']
    search_fields = ['message_id', 'error_message']
    readonly_fields = ['created_at', 'processed_at']