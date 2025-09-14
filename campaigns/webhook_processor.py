
import logging
from django.utils import timezone
from django.db import models

logger = logging.getLogger(__name__)


def process_360dialog_webhook(payload):
    """
    Process 360dialog webhook payload
    This function is separate to avoid circular imports
    """
    from .models import Message, Campaign  # Import here to avoid circular import
    
    try:
        # Handle Meta/WhatsApp Cloud API webhook structure
        if 'entry' in payload:
            # Meta webhook format
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if 'statuses' in value:
                        payload = value  # Extract the nested value
                        break
        
        # Process status updates
        if 'statuses' in payload:
            for status_update in payload['statuses']:
                message_id = status_update.get('id')
                status = status_update.get('status')
                timestamp = status_update.get('timestamp')
                recipient_id = status_update.get('recipient_id')
                
                logger.info(f"Processing status update: {message_id} -> {status}")
                
                # Find the message in our database
                try:
                    message = Message.objects.get(message_id=message_id)
                    old_status = message.status
                    
                    # Update message status based on webhook
                    if status == 'sent':
                        # Ignore webhook 'sent' status - message already marked as sent on API success
                        # Just log for debugging purposes
                        logger.info(f"Webhook 'sent' received for message {message_id} - already handled on API success")
                        
                    elif status == 'delivered':
                        # Only update if message is not already delivered or read
                        if message.status not in ['delivered', 'read']:
                            message.status = 'delivered'
                            message.delivered_at = timezone.now()
                            
                            # Update campaign counter only on first delivery
                            Campaign.objects.filter(id=message.campaign_id).update(
                                delivered_count=models.F('delivered_count') + 1
                            )
                        else:
                            logger.info(f"Message {message_id} already delivered/read, skipping duplicate webhook")
                        
                        # Import and trigger next message
                        from .tasks import send_next_message
                        logger.info(f"Message delivered to {message.phone_number}, triggering next message")
                        send_next_message.delay(message.campaign_id)
                        
                    elif status == 'read':
                        # Only update if message is not already read
                        if message.status != 'read':
                            message.status = 'read'
                            message.read_at = timezone.now()
                            
                            # Update campaign counter only on first read
                            Campaign.objects.filter(id=message.campaign_id).update(
                                read_count=models.F('read_count') + 1
                            )
                        else:
                            logger.info(f"Message {message_id} already read, skipping duplicate webhook")
                        
                    elif status == 'failed':
                        # Only update if message is not already failed
                        if message.status != 'failed':
                            message.status = 'failed'
                            message.failed_at = timezone.now()
                            
                            # Extract error details
                            errors = status_update.get('errors', [])
                            if errors:
                                error_msg = f"Error {errors[0].get('code')}: {errors[0].get('title')}"
                                message.error_message = error_msg
                            
                            # Update campaign counter only on first failure
                            Campaign.objects.filter(id=message.campaign_id).update(
                                failed_count=models.F('failed_count') + 1
                            )
                        else:
                            logger.info(f"Message {message_id} already failed, skipping duplicate webhook")
                        
                        # Import and check campaign completion
                        from .tasks import check_campaign_completion
                        check_campaign_completion.delay(message.campaign_id)
                    
                    message.save()
                    
                    logger.info(f"Updated message {message_id}: {old_status} -> {status}")
                    
                except Message.DoesNotExist:
                    logger.warning(f"Message not found for ID: {message_id}")
                except Exception as e:
                    logger.error(f"Error updating message {message_id}: {e}")
        
        # Process incoming messages (if needed)
        if 'messages' in payload:
            for incoming_msg in payload['messages']:
                logger.info(f"Received incoming message: {incoming_msg}")
        
        # Process errors
        if 'errors' in payload:
            for error in payload['errors']:
                logger.error(f"360dialog error: {error}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing 360dialog webhook: {e}")
        return False