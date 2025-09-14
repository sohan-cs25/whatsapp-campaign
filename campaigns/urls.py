
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CampaignViewSet,
    CampaignStatsView,
    FileUploadView,
    get_recent_messages
)
from .webhook_handler import WhatsAppWebhookView

app_name = 'campaigns'

# Create router for viewsets
router = DefaultRouter()
router.register(r'campaigns', CampaignViewSet, basename='campaign')

urlpatterns = [
    # ViewSet URLs
    path('', include(router.urls)),
    
    path('stats/', CampaignStatsView.as_view(), name='campaign-stats'),
    path('validate-file/', FileUploadView.as_view(), name='validate-file'),
    path('recent-messages/', get_recent_messages, name='recent-messages'),
    
    # WhatsApp Webhook endpoint
    path('webhook/whatsapp/', WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
]