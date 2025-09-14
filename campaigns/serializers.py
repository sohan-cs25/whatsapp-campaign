
from rest_framework import serializers
from .models import Campaign, UploadedFile, Message, WebhookLog
from django.contrib.auth.models import User
import os


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for individual messages"""
    
    class Meta:
        model = Message
        fields = [
            'id', 'phone_number', 'status', 'has_variables', 'variables',
            'has_media', 'media_url', 'sent_at', 'delivered_at', 'read_at',
            'error_message', 'retry_count'
        ]
        read_only_fields = ['id', 'sent_at', 'delivered_at', 'read_at']


class UploadedFileSerializer(serializers.ModelSerializer):
    """Serializer for uploaded files"""
    
    file_size = serializers.SerializerMethodField()
    
    class Meta:
        model = UploadedFile
        fields = [
            'id', 'file_name', 'file_path', 'file_type', 'file_size',
            'row_count', 'valid_rows', 'invalid_rows', 'status',
            'error_log', 'uploaded_at', 'processed_at'
        ]
        read_only_fields = ['id', 'file_type', 'uploaded_at', 'processed_at', 
                          'row_count', 'valid_rows', 'invalid_rows', 'status']
    
    def get_file_size(self, obj):
        """Get file size in KB"""
        if obj.file_path and os.path.exists(obj.file_path.path):
            size = os.path.getsize(obj.file_path.path)
            return round(size / 1024, 2)  # Return size in KB
        return 0


class CampaignSerializer(serializers.ModelSerializer):
    """Serializer for campaigns"""
    
    user = serializers.StringRelatedField(read_only=True)
    file = UploadedFileSerializer(read_only=True)
    success_rate = serializers.ReadOnlyField()
    duration = serializers.SerializerMethodField()
    messages_sample = serializers.SerializerMethodField()
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'user', 'template_name', 'status', 'total_recipients',
            'sent_count', 'delivered_count', 'read_count', 'failed_count',
            'success_rate', 'file', 'created_at', 'started_at', 
            'completed_at', 'duration', 'messages_sample'
        ]
        read_only_fields = [
            'id', 'user', 'total_recipients', 'sent_count', 'delivered_count',
            'read_count', 'failed_count', 'created_at', 'started_at', 
            'completed_at', 'status'
        ]
    
    def get_duration(self, obj):
        """Calculate campaign duration"""
        if obj.started_at and obj.completed_at:
            duration = obj.completed_at - obj.started_at
            return str(duration)
        return None
    
    def get_messages_sample(self, obj):
        """Get sample of messages (first 5)"""
        messages = obj.messages.all()[:5]
        return MessageSerializer(messages, many=True).data


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating campaigns"""
    
    file = serializers.FileField(write_only=True, required=True)
    
    class Meta:
        model = Campaign
        fields = ['template_name', 'file']
    
    def validate_file(self, value):
        """Validate uploaded file"""
        # Check file extension
        ext = os.path.splitext(value.name)[1].lower()
        valid_extensions = ['.csv', '.xlsx', '.xls']
        
        if ext not in valid_extensions:
            raise serializers.ValidationError(
                f"Unsupported file type. Allowed types: {', '.join(valid_extensions)}"
            )
        
        # Check file size (max 10MB)
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File size cannot exceed 10MB")
        
        return value
    
    def create(self, validated_data):
        """Create campaign with file"""
        file = validated_data.pop('file')
        user = self.context['request'].user
        
        # Create campaign
        campaign = Campaign.objects.create(
            user=user,
            template_name=validated_data['template_name'],
            status='draft'
        )
        
        # Create uploaded file record
        ext = os.path.splitext(file.name)[1].lower()
        uploaded_file = UploadedFile.objects.create(
            user=user,
            campaign=campaign,
            file_name=file.name,
            file_path=file,
            file_type=ext[1:],  # Remove the dot
            status='pending'
        )
        
        # Trigger async file processing here (we'll add this later)
        # process_uploaded_file.delay(uploaded_file.id)
        
        return campaign


class CampaignListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for campaign list"""
    
    user = serializers.StringRelatedField(read_only=True)
    file_name = serializers.CharField(source='file.file_name', read_only=True)
    success_rate = serializers.ReadOnlyField()
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'user', 'template_name', 'status', 'total_recipients',
            'sent_count', 'delivered_count', 'success_rate', 'file_name',
            'created_at'
        ]


class CampaignStatusSerializer(serializers.ModelSerializer):
    """Serializer for campaign status updates"""
    
    class Meta:
        model = Campaign
        fields = ['status']
    
    def validate_status(self, value):
        """Validate status transitions"""
        if self.instance:
            current_status = self.instance.status
            
            # Define valid transitions
            valid_transitions = {
                'draft': ['pending', 'failed'],
                'pending': ['running', 'paused', 'failed'],
                'running': ['paused', 'completed', 'failed'],
                'paused': ['running', 'failed'],
                'completed': [],
                'failed': ['pending']
            }
            
            if value not in valid_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"Cannot change status from '{current_status}' to '{value}'"
                )
        
        return value


class CampaignStatsSerializer(serializers.Serializer):
    """Serializer for campaign statistics"""
    
    total_campaigns = serializers.IntegerField()
    active_campaigns = serializers.IntegerField()
    completed_campaigns = serializers.IntegerField()
    total_messages_sent = serializers.IntegerField()
    total_recipients = serializers.IntegerField()
    overall_success_rate = serializers.FloatField()
    campaigns_by_status = serializers.DictField()


class MessageStatusSerializer(serializers.ModelSerializer):
    """Serializer for message status distribution"""
    
    campaign_name = serializers.CharField(source='campaign.template_name', read_only=True)
    
    class Meta:
        model = Message
        fields = [
            'id', 'campaign_name', 'phone_number', 'status', 
            'sent_at', 'delivered_at', 'error_message'
        ]


class WebhookLogSerializer(serializers.ModelSerializer):
    """Serializer for webhook logs"""
    
    class Meta:
        model = WebhookLog
        fields = [
            'id', 'event_type', 'raw_payload', 'processed',
            'message_id', 'error_message', 'created_at', 'processed_at'
        ]
        read_only_fields = '__all__'