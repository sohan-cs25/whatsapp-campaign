
import os
from celery import Celery
from decouple import config

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')

# Create Celery app
app = Celery('whatsapp_campaign')

# Load configuration from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all registered Django apps
app.autodiscover_tasks()

# # Configure task routing
# app.conf.task_routes = {
#     'campaigns.tasks.process_uploaded_file': {'queue': 'file_processing'},
#     'campaigns.tasks.send_message': {'queue': 'messages'},
#     'campaigns.tasks.process_webhook': {'queue': 'webhooks'},
# }

# # Task configuration
# app.conf.task_acks_late = True
# app.conf.worker_prefetch_multiplier = 1
# app.conf.task_time_limit = 30 * 60  # 30 minutes
# app.conf.task_soft_time_limit = 25 * 60  # 25 minutes

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')