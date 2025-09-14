from django.shortcuts import render

# Create your views here.

# campaigns/views.py (showing only the imports and the methods that use tasks)

from rest_framework import status, viewsets, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count, Q, Sum, Avg
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Campaign, UploadedFile, Message, WebhookLog
from .serializers import (
    CampaignSerializer,
    CampaignCreateSerializer,
    CampaignListSerializer,
    CampaignStatusSerializer,
    CampaignStatsSerializer,
    MessageSerializer,
    MessageStatusSerializer,
    UploadedFileSerializer,
    WebhookLogSerializer
)
# Remove the import of tasks from here
import logging
import pandas as pd
import json

logger = logging.getLogger(__name__)


class CampaignViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Campaign CRUD operations
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['template_name']
    ordering_fields = ['created_at', 'status', 'total_recipients']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get campaigns for current user only"""
        return Campaign.objects.filter(user=self.request.user).select_related('file')
    
    def get_serializer_class(self):
        """Use different serializers for different actions"""
        if self.action == 'create':
            return CampaignCreateSerializer
        elif self.action == 'list':
            return CampaignListSerializer
        elif self.action in ['update_status']:
            return CampaignStatusSerializer
        return CampaignSerializer
    
    def create(self, request, *args, **kwargs):
        """
        Create new campaign with file upload
        """
        print(f"DEBUG: Creating campaign with data: {request.data}")
        print(f"DEBUG: Files: {request.FILES}")
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()
        
        print(f"DEBUG: Campaign created: {campaign.id}")
        print(f"DEBUG: Campaign has file: {campaign.file}")
        
        # Import task here to avoid circular import
        from .tasks import process_uploaded_file
        
        # Process file asynchronously
        if campaign.file:
            print(f"DEBUG: Processing file {campaign.file.id} for campaign {campaign.id}")
            # Trigger Celery task
            result = process_uploaded_file.delay(campaign.file.id)
            print(f"DEBUG: Celery task triggered: {result}")
            logger.info(f"Campaign created: {campaign.id}, processing file: {campaign.file.id}")
        else:
            print("DEBUG: No file found for campaign!")
        
        return Response({
            'success': True,
            'message': 'Campaign created successfully. File is being processed.',
            'campaign': CampaignSerializer(campaign).data
        }, status=status.HTTP_201_CREATED)
    
    def destroy(self, request, *args, **kwargs):
        """Delete campaign if not running"""
        campaign = self.get_object()
        
        if campaign.status == 'running':
            return Response({
                'success': False,
                'error': 'Cannot delete a running campaign. Please pause or stop it first.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        campaign.delete()
        return Response({
            'success': True,
            'message': 'Campaign deleted successfully'
        }, status=status.HTTP_204_NO_CONTENT)
    
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """
        Start a campaign
        """
        campaign = self.get_object()
        
        if campaign.status not in ['pending', 'paused']:
            return Response({
                'success': False,
                'error': f'Cannot start campaign with status: {campaign.status}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if campaign.total_recipients == 0:
            return Response({
                'success': False,
                'error': 'No valid recipients found. Please upload a file first.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Import task here to avoid circular import
        from .tasks import start_campaign_task
        
        # Start campaign asynchronously
        start_campaign_task.delay(campaign.id)
        
        campaign.status = 'running'
        campaign.started_at = timezone.now()
        campaign.save()
        
        logger.info(f"Campaign started: {campaign.id}")
        
        return Response({
            'success': True,
            'message': 'Campaign started successfully',
            'campaign': CampaignSerializer(campaign).data
        })
    
    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """
        Pause a running campaign
        """
        campaign = self.get_object()
        
        if campaign.status != 'running':
            return Response({
                'success': False,
                'error': 'Can only pause running campaigns'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        campaign.status = 'paused'
        campaign.save()
        
        logger.info(f"Campaign paused: {campaign.id}")
        
        return Response({
            'success': True,
            'message': 'Campaign paused successfully',
            'campaign': CampaignSerializer(campaign).data
        })
    
    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        """
        Resume a paused campaign
        """
        campaign = self.get_object()
        
        if campaign.status != 'paused':
            return Response({
                'success': False,
                'error': 'Can only resume paused campaigns'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        campaign.status = 'running'
        campaign.save()
        
        # Import task here to avoid circular import
        from .tasks import start_campaign_task
        
        # Resume sending messages
        start_campaign_task.delay(campaign.id)
        
        logger.info(f"Campaign resumed: {campaign.id}")
        
        return Response({
            'success': True,
            'message': 'Campaign resumed successfully',
            'campaign': CampaignSerializer(campaign).data
        })
    
    @action(detail=True, methods=['post'], url_path='check-status')
    def check_status(self, request, pk=None):
        """
        Check campaign status and update if all messages are sent
        """
        campaign = self.get_object()
        
        # Check if campaign should be marked as completed
        if campaign.status == 'running':
            # Check for any pending messages (queued or sending)
            pending_messages = Message.objects.filter(
                campaign_id=campaign.id,
                status__in=['queued', 'sending']
            ).count()
            
            if pending_messages == 0:
                # All messages processed, mark campaign as completed
                campaign.status = 'completed'
                campaign.completed_at = timezone.now()
                campaign.save()
                
                logger.info(f"Campaign {campaign.id} marked as completed after status check")
                
                return Response({
                    'success': True,
                    'message': 'Campaign status updated to completed',
                    'campaign': CampaignSerializer(campaign).data,
                    'updated': True
                })
            else:
                return Response({
                    'success': True,
                    'message': f'Campaign still has {pending_messages} pending messages',
                    'campaign': CampaignSerializer(campaign).data,
                    'pending_messages': pending_messages,
                    'updated': False
                })
        
        return Response({
            'success': True,
            'message': f'Campaign status is {campaign.status}',
            'campaign': CampaignSerializer(campaign).data,
            'updated': False
        })
    

    
    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """
        Get messages for a campaign with pagination
        """
        campaign = self.get_object()
        messages = Message.objects.filter(campaign=campaign)
        
        # Filter by status if provided
        status_filter = request.query_params.get('status', None)
        if status_filter:
            messages = messages.filter(status=status_filter)
        
        # Pagination
        page = self.paginate_queryset(messages)
        if page is not None:
            serializer = MessageSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = MessageSerializer(messages, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get detailed statistics for a campaign
        """
        campaign = self.get_object()
        
        # Get message status distribution
        status_distribution = Message.objects.filter(campaign=campaign).values('status').annotate(
            count=Count('id')
        )
        
        # Calculate average delivery time
        delivered_messages = Message.objects.filter(
            campaign=campaign,
            delivered_at__isnull=False,
            sent_at__isnull=False
        )
        
        avg_delivery_time = None
        if delivered_messages.exists():
            # This would need raw SQL or post-processing
            # For now, we'll calculate it differently
            total_time = 0
            count = 0
            for msg in delivered_messages[:100]:  # Sample for performance
                if msg.delivered_at and msg.sent_at:
                    diff = (msg.delivered_at - msg.sent_at).total_seconds()
                    total_time += diff
                    count += 1
            if count > 0:
                avg_delivery_time = total_time / count
        
        stats = {
            'campaign_id': campaign.id,
            'template_name': campaign.template_name,
            'status': campaign.status,
            'total_recipients': campaign.total_recipients,
            'sent_count': campaign.sent_count,
            'delivered_count': campaign.delivered_count,
            'read_count': campaign.read_count,
            'failed_count': campaign.failed_count,
            'success_rate': campaign.success_rate,
            'status_distribution': list(status_distribution),
            'average_delivery_time_seconds': avg_delivery_time,
            'started_at': campaign.started_at,
            'completed_at': campaign.completed_at
        }
        
        return Response({
            'success': True,
            'statistics': stats
        })
    
    @action(detail=True, methods=['get'])
    def download_report(self, request, pk=None):
        """
        Download campaign report as CSV
        """
        campaign = self.get_object()
        messages = Message.objects.filter(campaign=campaign).values(
            'phone_number', 'status', 'sent_at', 'delivered_at', 
            'read_at', 'error_message'
        )
        
        # Convert to DataFrame
        df = pd.DataFrame(list(messages))
        
        # Create CSV response
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="campaign_{campaign.id}_report.csv"'
        
        df.to_csv(response, index=False)
        return response


class CampaignStatsView(APIView):
    """
    Get overall campaign statistics for the user
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get campaign statistics"""
        user_campaigns = Campaign.objects.filter(user=request.user)
        
        total_campaigns = user_campaigns.count()
        active_campaigns = user_campaigns.filter(status='running').count()
        completed_campaigns = user_campaigns.filter(status='completed').count()
        
        # Aggregate message statistics
        total_sent = user_campaigns.aggregate(Sum('sent_count'))['sent_count__sum'] or 0
        total_recipients = user_campaigns.aggregate(Sum('total_recipients'))['total_recipients__sum'] or 0
        
        # Calculate overall success rate
        success_rate = (total_sent / total_recipients * 100) if total_recipients > 0 else 0
        
        # Campaigns by status
        status_distribution = user_campaigns.values('status').annotate(
            count=Count('id')
        )
        campaigns_by_status = {item['status']: item['count'] for item in status_distribution}
        
        stats = {
            'total_campaigns': total_campaigns,
            'active_campaigns': active_campaigns,
            'completed_campaigns': completed_campaigns,
            'total_messages_sent': total_sent,
            'total_recipients': total_recipients,
            'overall_success_rate': round(success_rate, 2),
            'campaigns_by_status': campaigns_by_status
        }
        
        serializer = CampaignStatsSerializer(stats)
        return Response({
            'success': True,
            'statistics': serializer.data
        })


class FileUploadView(APIView):
    """
    Handle file upload and validation
    """
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    
    def post(self, request):
        """
        Upload and validate a CSV/Excel file
        
        This endpoint validates the file without creating a campaign
        """
        file = request.FILES.get('file')
        
        if not file:
            return Response({
                'success': False,
                'error': 'No file provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate file extension
        import os
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ['.csv', '.xlsx', '.xls']:
            return Response({
                'success': False,
                'error': f'Invalid file type: {ext}. Allowed types: .csv, .xlsx, .xls'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Read file
            if ext == '.csv':
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
            
            # Validate required columns
            required_columns = ['phone', 'has_variables', 'variables', 'has_media', 'media_url']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return Response({
                    'success': False,
                    'error': f'Missing required columns: {", ".join(missing_columns)}',
                    'required_columns': required_columns,
                    'found_columns': list(df.columns)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate data
            validation_errors = []
            valid_rows = 0
            
            for index, row in df.iterrows():
                errors = []
                
                # Validate phone number
                phone = str(row['phone']).strip()
                if not phone or phone == 'nan':
                    errors.append('Invalid phone number')
                
                # Validate variables if has_variables is True
                if row['has_variables'] and pd.isna(row['variables']):
                    errors.append('Variables required but not provided')
                
                # Validate media URL if has_media is True
                if row['has_media'] and pd.isna(row['media_url']):
                    errors.append('Media URL required but not provided')
                
                if errors:
                    validation_errors.append({
                        'row': index + 2,  # +2 because Excel rows start at 1 and header is row 1
                        'errors': errors
                    })
                else:
                    valid_rows += 1
            
            response_data = {
                'success': True,
                'file_info': {
                    'name': file.name,
                    'total_rows': len(df),
                    'valid_rows': valid_rows,
                    'invalid_rows': len(validation_errors),
                    'columns': list(df.columns)
                }
            }
            
            if validation_errors:
                response_data['validation_errors'] = validation_errors[:10]  # Show first 10 errors
                response_data['message'] = f'File has {len(validation_errors)} validation errors'
            else:
                response_data['message'] = 'File validated successfully'
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"File validation error: {str(e)}")
            return Response({
                'success': False,
                'error': f'Error processing file: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_recent_messages(request):
    """
    Get recent messages across all campaigns
    """
    messages = Message.objects.filter(
        campaign__user=request.user
    ).select_related('campaign').order_by('-sent_at')[:50]
    
    serializer = MessageStatusSerializer(messages, many=True)
    return Response({
        'success': True,
        'messages': serializer.data
    })