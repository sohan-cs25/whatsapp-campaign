
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Configuration
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:8000/api')

# App Configuration
APP_NAME = "WhatsApp Campaign Manager"
APP_ICON = "📱"

# Session Configuration
SESSION_TIMEOUT = 3600  # 1 hour in seconds

# UI Configuration
PAGE_ICON = "📱"
LAYOUT = "wide"

# Color Theme
COLORS = {
    'primary': '#25D366',      # WhatsApp Green
    'secondary': '#128C7E',    # WhatsApp Dark Green
    'success': '#4CAF50',      
    'warning': '#FF9800',      
    'danger': '#F44336',       
    'info': '#2196F3',
    'background': '#FAFAFA',   
    'card': '#FFFFFF',         
    'text': '#212121',         
    'text_secondary': '#757575' 
}

# Status Colors
STATUS_COLORS = {
    'draft': '#9E9E9E',
    'pending': '#FF9800',
    'running': '#2196F3',
    'paused': '#FF5722',
    'completed': '#4CAF50',
    'failed': '#F44336'
}

# Message Status Icons
STATUS_ICONS = {
    'queued': '⏳',
    'sending': '📤',
    'sent': '✓',
    'delivered': '✓✓',
    'read': '👁️',
    'failed': '❌'
}
