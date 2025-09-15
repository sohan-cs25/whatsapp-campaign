"""
Configuration settings for Orders Streamlit App
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Configuration
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000')

# App Configuration
APP_NAME = "WhatsApp Order Processing"
APP_ICON = "🛒"
PAGE_ICON = "🛒"
LAYOUT = "wide"

# Session Configuration
SESSION_TIMEOUT = 3600  # 1 hour in seconds

# UI Configuration
COLORS = {
    'primary': '#1f77b4',      # Blue
    'secondary': '#ff7f0e',    # Orange
    'success': '#2ca02c',      # Green
    'warning': '#ffbb33',      # Yellow
    'danger': '#d62728',       # Red
    'info': '#17a2b8',         # Cyan
    'background': '#ffffff',   # White
    'sidebar': '#f8f9fa'       # Light gray
}

# Status Colors for Orders
STATUS_COLORS = {
    'pending': '#ffbb33',
    'sent': '#17a2b8',
    'delivered': '#2ca02c',
    'read': '#28a745',
    'failed': '#d62728'
}

# Message Type Colors
MESSAGE_TYPE_COLORS = {
    'order': '#28a745',
    'enquiry': '#17a2b8',
    'review': '#6f42c1',
    'address': '#fd7e14',
    'announcement': '#6c757d',
    'general': '#e9ecef'
}

# File Upload Settings
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_FILE_TYPES = ['txt']
ALLOWED_VALIDATION_TYPES = ['xlsx', 'csv']

# Processing Settings
PROCESSING_TIMEOUT = 300  # 5 minutes
STREAMING_TIMEOUT = 600   # 10 minutes for large files

# API Endpoints
API_ENDPOINTS = {
    'auth': {
        'login': '/auth/login/',
        'signup': '/auth/signup/',
        'verify_token': '/auth/verify-token/',
        'user_profile': '/auth/user/',
    },
    'orders': {
        'chatfiles': '/orders/chatfiles/',
        'processed_files': '/orders/processed-files/',
        'validated_files': '/orders/validated-files/',
        'orders': '/orders/orders/',
        'stats': '/orders/stats/',
        'analytics': '/orders/analytics/',
        'process_stream': '/orders/process-stream/',
        'send_messages': '/orders/send-messages/',
    }
}

# Default pagination
DEFAULT_PAGE_SIZE = 20