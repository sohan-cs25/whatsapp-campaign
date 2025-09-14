from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ChatFileViewSet,
    ParsedChatFileViewSet,
    ValidatedFileViewSet,
    OrderViewSet,
    processing_stats,
    process_stream
)

app_name = 'orders'

# Create router for viewsets
router = DefaultRouter()
router.register(r'chatfiles', ChatFileViewSet, basename='chatfile')
router.register(r'processed-files', ParsedChatFileViewSet, basename='parsedchatfile')
router.register(r'validated-files', ValidatedFileViewSet, basename='validatedfile')
router.register(r'orders', OrderViewSet, basename='order')

urlpatterns = [
    # ViewSet URLs
    path('', include(router.urls)),

    # Custom endpoints
    path('stats/', processing_stats, name='processing-stats'),
    path('process-stream/<uuid:file_id>/', process_stream, name='process-stream'),
]