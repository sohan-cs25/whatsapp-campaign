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
    send_order_messages,
    resend_payment_success_message
)
from .review_views import (CustomerContactViewSet, ProductViewSet, review_orders, update_review_order,
                           approve_orders, send_approved_orders, refresh_review_orders)

app_name = 'orders'

# Create router for viewsets
router = DefaultRouter()
router.register(r'chatfiles', ChatFileViewSet, basename='chatfile')
router.register(r'processed-files', ParsedChatFileViewSet, basename='parsedchatfile')
router.register(r'validated-files', ValidatedFileViewSet, basename='validatedfile')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'customers', CustomerContactViewSet, basename='customer')

urlpatterns = [
    # Review flow (before the router so 'review/...' is matched first)
    path('review/orders/<uuid:order_id>/', update_review_order, name='review-order-update'),
    path('review/<uuid:parsed_file_id>/', review_orders, name='review-orders'),
    path('review/<uuid:parsed_file_id>/approve/', approve_orders, name='review-approve'),
    path('review/<uuid:parsed_file_id>/send/', send_approved_orders, name='review-send'),
    path('review/<uuid:parsed_file_id>/refresh/', refresh_review_orders, name='review-refresh'),

    # ViewSet URLs
    path('', include(router.urls)),

    # Custom endpoints
    path('stats/', processing_stats, name='processing-stats'),
    path('analytics/', analytics_dashboard, name='analytics-dashboard'),
    path('process-stream/<uuid:file_id>/', process_stream, name='process-stream'),
    path('send-messages/', send_order_messages, name='send-order-messages'),
    path('orders/<uuid:order_id>/resend-payment-success/', resend_payment_success_message, name='resend-payment-success'),
]