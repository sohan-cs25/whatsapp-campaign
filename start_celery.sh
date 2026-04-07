#!/bin/bash

# Start Celery Worker
echo "Starting Celery Worker..."
celery -A whatsapp_campaign worker --loglevel=info --logfile=logs/celery_worker1.log --detach

# Start Celery Beat (for periodic tasks)
echo "Starting Celery Beat..."
celery -A whatsapp_campaign beat --loglevel=info --logfile=logs/celery_beat1.log --detach

echo "Celery services started!"
echo "Check logs at:"
echo "  - logs/celery_worker1.log"
echo "  - logs/celery_beat1.log"
