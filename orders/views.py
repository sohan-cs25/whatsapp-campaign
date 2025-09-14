from django.shortcuts import render
from django.http import HttpResponse, FileResponse, Http404, StreamingHttpResponse
from django.core.exceptions import ValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from django.db.models import Count, Q, Sum
from django.utils import timezone
import os
import logging
import mimetypes
import json
import time

from .models import ChatFile, ParsedChatFile, ValidatedFile, Order, WebhookEvent
from .serializers import (
    ChatFileSerializer, ChatFileListSerializer,
    ParsedChatFileSerializer, ParsedChatFileListSerializer,
    ValidatedFileSerializer, ValidatedFileListSerializer,
    OrderSerializer, OrderListSerializer,
    WebhookEventSerializer, FileUploadProgressSerializer,
    ProcessingStatsSerializer
)

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ChatFileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ChatFile CRUD operations
    Handles WhatsApp .txt file uploads
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['filename']
    ordering_fields = ['uploaded_at', 'is_processed']
    ordering = ['-uploaded_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return ChatFile.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return ChatFileListSerializer
        return ChatFileSerializer

    def create(self, request, *args, **kwargs):
        """Upload a new chat file"""
        try:
            if 'filepath' not in request.FILES:
                return Response({
                    'error': 'No file provided. Please upload a file.'
                }, status=status.HTTP_400_BAD_REQUEST)

            uploaded_file = request.FILES['filepath']

            # Validate file type
            if not uploaded_file.name.endswith(('.txt', '.csv')):
                return Response({
                    'error': 'Invalid file type. Only .txt and .csv files are allowed.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Validate file size (max 50MB)
            if uploaded_file.size > 50 * 1024 * 1024:
                return Response({
                    'error': 'File too large. Maximum size is 50MB.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Set filename and filetype
            data = request.data.copy()
            data['filename'] = uploaded_file.name
            data['filetype'] = 'text' if uploaded_file.name.endswith('.txt') else 'csv'

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                chat_file = serializer.save()
                logger.info(f"Chat file uploaded: {chat_file.filename} by user {request.user.username}")

                return Response({
                    'success': True,
                    'message': 'File uploaded successfully',
                    'data': serializer.data
                }, status=status.HTTP_201_CREATED)

            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error uploading chat file: {str(e)}")
            return Response({
                'error': 'An error occurred while uploading the file.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """Trigger AI processing of chat file"""
        chat_file = self.get_object()

        if chat_file.is_processed:
            return Response({
                'error': 'File has already been processed'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Trigger Celery task for processing
        from .tasks import process_chat_file
        process_chat_file.delay(str(chat_file.id))

        return Response({
            'success': True,
            'message': 'File processing started',
            'file_id': chat_file.id
        })


class ParsedChatFileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ParsedChatFile operations
    Handles AI-processed chat files
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['processed_at', 'total_orders']
    ordering = ['-processed_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return ParsedChatFile.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return ParsedChatFileListSerializer
        return ParsedChatFileSerializer

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download processed chat file"""
        try:
            parsed_file = self.get_object()
            file_path = parsed_file.processed_file_path.path

            if not os.path.exists(file_path):
                raise Http404("File not found")

            # Update download tracking
            parsed_file.downloaded_at = timezone.now()
            parsed_file.downloaded_by = request.user
            parsed_file.save()

            # Determine content type
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = 'application/octet-stream'

            response = FileResponse(
                open(file_path, 'rb'),
                content_type=content_type,
                as_attachment=True,
                filename=parsed_file.file_name
            )

            logger.info(f"Downloaded processed file: {parsed_file.file_name} by user {request.user.username}")
            return response

        except Exception as e:
            logger.error(f"Error downloading processed file: {str(e)}")
            raise Http404("File not found")


class ValidatedFileViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ValidatedFile operations
    Handles human-validated order files
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['file_name']
    ordering_fields = ['uploaded_at', 'orders_extracted']
    ordering = ['-uploaded_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return ValidatedFile.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return ValidatedFileListSerializer
        return ValidatedFileSerializer

    def create(self, request, *args, **kwargs):
        """Upload a validated file"""
        try:
            if 'filepath' not in request.FILES:
                return Response({
                    'error': 'No file provided. Please upload a file.'
                }, status=status.HTTP_400_BAD_REQUEST)

            uploaded_file = request.FILES['filepath']

            # Validate file type
            if not uploaded_file.name.endswith(('.xlsx', '.csv')):
                return Response({
                    'error': 'Invalid file type. Only .xlsx and .csv files are allowed.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Set file details
            data = request.data.copy()
            data['file_name'] = uploaded_file.name
            data['filetype'] = 'xlsx' if uploaded_file.name.endswith('.xlsx') else 'csv'

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                validated_file = serializer.save()
                logger.info(f"Validated file uploaded: {validated_file.file_name} by user {request.user.username}")

                return Response({
                    'success': True,
                    'message': 'Validated file uploaded successfully',
                    'data': serializer.data
                }, status=status.HTTP_201_CREATED)

            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error uploading validated file: {str(e)}")
            return Response({
                'error': 'An error occurred while uploading the file.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download validated file"""
        try:
            validated_file = self.get_object()
            file_path = validated_file.filepath.path

            if not os.path.exists(file_path):
                raise Http404("File not found")

            # Determine content type
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = 'application/octet-stream'

            response = FileResponse(
                open(file_path, 'rb'),
                content_type=content_type,
                as_attachment=True,
                filename=validated_file.file_name
            )

            logger.info(f"Downloaded validated file: {validated_file.file_name} by user {request.user.username}")
            return response

        except Exception as e:
            logger.error(f"Error downloading validated file: {str(e)}")
            raise Http404("File not found")

    @action(detail=True, methods=['post'])
    def extract_orders(self, request, pk=None):
        """Extract orders from validated file"""
        validated_file = self.get_object()

        if validated_file.is_processed:
            return Response({
                'error': 'Orders have already been extracted from this file'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Trigger Celery task for order extraction
        from .tasks import extract_orders_from_file
        extract_orders_from_file.delay(str(validated_file.id))

        return Response({
            'success': True,
            'message': 'Order extraction started',
            'file_id': validated_file.id
        })


class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Order operations
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['number', 'payment_reference_id']
    ordering_fields = ['created_at', 'amount', 'status']
    ordering = ['-created_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return Order.objects.filter(validated_file__user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        return OrderSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def processing_stats(request):
    """
    Get processing statistics for current user
    """
    user = request.user

    stats = {
        'total_files_uploaded': ChatFile.objects.filter(user=user).count(),
        'total_files_processed': ParsedChatFile.objects.filter(user=user).count(),
        'total_files_validated': ValidatedFile.objects.filter(user=user).count(),
        'total_orders_extracted': Order.objects.filter(validated_file__user=user).count(),
        'total_messages_sent': Order.objects.filter(validated_file__user=user, status__in=['sent', 'delivered', 'read']).count(),
    }

    # Calculate processing success rate
    if stats['total_files_uploaded'] > 0:
        stats['processing_success_rate'] = (stats['total_files_processed'] / stats['total_files_uploaded']) * 100
    else:
        stats['processing_success_rate'] = 0.0

    serializer = ProcessingStatsSerializer(stats)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def process_stream(request, file_id):
    """
    Stream processing progress for a chat file
    """
    def stream_progress():
        try:
            # Check if file exists and belongs to user
            chat_file = ChatFile.objects.get(
                id=file_id,
                user=request.user
            )

            # Send initial status
            yield f"data: {json.dumps({'status': 'starting', 'message': 'Initializing processing...', 'progress': 0})}\n\n"

            # Monitor processing progress
            max_wait_time = 600  # 10 minutes
            check_interval = 2   # Check every 2 seconds
            elapsed_time = 0

            while elapsed_time < max_wait_time:
                # Refresh from database
                chat_file.refresh_from_db()

                if chat_file.processing_error:
                    yield f"data: {json.dumps({'status': 'error', 'message': chat_file.processing_error, 'progress': 0})}\n\n"
                    break

                if chat_file.is_processed:
                    # Check if processed file was created
                    try:
                        processed_file = chat_file.processed_file
                        yield f"data: {json.dumps({'status': 'completed', 'message': 'Processing completed successfully!', 'progress': 100, 'processed_file_id': str(processed_file.id)})}\n\n"
                    except ParsedChatFile.DoesNotExist:
                        yield f"data: {json.dumps({'status': 'error', 'message': 'Processing completed but no output file found', 'progress': 0})}\n\n"
                    break

                # Calculate rough progress based on elapsed time
                # This is a simple estimation - you could make this more sophisticated
                estimated_progress = min(int((elapsed_time / 300) * 80), 80)  # Cap at 80% until completion

                if elapsed_time < 30:
                    message = "Parsing chat messages..."
                    progress = estimated_progress
                elif elapsed_time < 120:
                    message = "Classifying messages with AI..."
                    progress = min(estimated_progress + 10, 85)
                else:
                    message = "Generating final output file..."
                    progress = min(estimated_progress + 15, 95)

                yield f"data: {json.dumps({'status': 'processing', 'message': message, 'progress': progress})}\n\n"

                time.sleep(check_interval)
                elapsed_time += check_interval

            # If we exit the loop without completion, it's a timeout
            if not chat_file.is_processed and not chat_file.processing_error:
                yield f"data: {json.dumps({'status': 'timeout', 'message': 'Processing is taking longer than expected. Please check back later.', 'progress': 0})}\n\n"

        except ChatFile.DoesNotExist:
            yield f"data: {json.dumps({'status': 'error', 'message': 'File not found or access denied', 'progress': 0})}\n\n"
        except Exception as e:
            logger.error(f"Error in process stream: {str(e)}")
            yield f"data: {json.dumps({'status': 'error', 'message': 'An unexpected error occurred', 'progress': 0})}\n\n"

    response = StreamingHttpResponse(
        stream_progress(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['Connection'] = 'keep-alive'
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Headers'] = 'Cache-Control'

    return response
