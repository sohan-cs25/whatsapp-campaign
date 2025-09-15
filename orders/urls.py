from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ChatFileViewSet,
    ParsedChatFileViewSet,
    ValidatedFileViewSet,
    OrderViewSet,
    processing_stats,
    analytics_dashboard,
    process_stream,
    send_order_messages
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
    path('analytics/', analytics_dashboard, name='analytics-dashboard'),
    path('process-stream/<uuid:file_id>/', process_stream, name='process-stream'),
    path('send-messages/', send_order_messages, name='send-order-messages'),
]