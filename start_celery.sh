#!/bin/bash

# Start Celery Worker
echo "Starting Celery Worker..."
celery -A whatsapp_campaign worker --loglevel=info --logfile=logs/celery_worker.log --detach

# Start Celery Beat (for periodic tasks)
echo "Starting Celery Beat..."
celery -A whatsapp_campaign beat --loglevel=info --logfile=logs/celery_beat.log --detach

echo "Celery services started!"
echo "Check logs at:"
echo "  - logs/celery_worker.log"
echo "  - logs/celery_beat.log"