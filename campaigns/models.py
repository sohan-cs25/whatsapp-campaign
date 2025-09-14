from django.db import models

# Create your models here.

from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
import json


class Campaign(models.Model):
    """Campaign model to track WhatsApp marketing campaigns"""
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaigns')
    template_name = models.CharField(max_length=255, help_text="WhatsApp template name")
    total_recipients = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    delivered_count = models.IntegerField(default=0)
    read_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'campaigns'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.template_name} - {self.user.username} - {self.status}"
    
    @property
    def success_rate(self):
        if self.total_recipients == 0:
            return 0
        return (self.sent_count / self.total_recipients) * 100


class UploadedFile(models.Model):
    """Track uploaded CSV/Excel files for campaigns"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    campaign = models.OneToOneField(Campaign, on_delete=models.CASCADE, related_name='file')
    file_name = models.CharField(max_length=255)
    file_path = models.FileField(
        upload_to='uploads/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['csv', 'xlsx', 'xls'])]
    )
    file_type = models.CharField(max_length=10)
    row_count = models.IntegerField(default=0)
    valid_rows = models.IntegerField(default=0)
    invalid_rows = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_log = models.JSONField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'uploaded_files'
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.file_name} - {self.status}"


class Message(models.Model):
    """Individual message tracking for each recipient"""
    
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ]
    
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='messages')
    phone_number = models.CharField(max_length=20, db_index=True)
    whatsapp_id = models.CharField(max_length=50, null=True, blank=True)
    has_variables = models.BooleanField(default=False)
    variables = models.JSONField(null=True, blank=True, help_text="Template variables as JSON")
    has_media = models.BooleanField(default=False)
    media_url = models.URLField(max_length=500, null=True, blank=True)
    message_id = models.CharField(max_length=100, null=True, blank=True, db_index=True, 
                                  help_text="WhatsApp message ID")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    response_code = models.IntegerField(null=True, blank=True)
    response_json = models.JSONField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    
    class Meta:
        db_table = 'messages'
        ordering = ['id']  # Maintain order for sequential sending
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['message_id']),
            models.Index(fields=['phone_number']),
        ]
    
    def __str__(self):
        return f"{self.phone_number} - {self.status}"
    
    def get_variables_list(self):
        """Return variables as a list"""
        if self.variables:
            if isinstance(self.variables, list):
                return self.variables
            elif isinstance(self.variables, str):
                try:
                    return json.loads(self.variables)
                except:
                    return [self.variables]
        return []


class WebhookLog(models.Model):
    """Log all webhook events from WhatsApp"""
    
    event_type = models.CharField(max_length=50)
    raw_payload = models.JSONField()
    processed = models.BooleanField(default=False)
    message_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'webhook_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['processed', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.created_at}"