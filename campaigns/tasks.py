
from celery import shared_task
from django.utils import timezone
from django.db import models
import pandas as pd
import json
import logging
import time
from .models import Campaign, UploadedFile, Message, WebhookLog
from .whatsapp_360_client import WhatsApp360Client
from .webhook_processor import process_360dialog_webhook

logger = logging.getLogger(__name__)


@shared_task
def process_uploaded_file(file_id):
    """
    Process uploaded CSV/Excel file and create messages
    """
    print(f"DEBUG: Processing file {file_id}")
    try:
        uploaded_file = UploadedFile.objects.get(id=file_id)
        uploaded_file.status = 'processing'
        uploaded_file.save()
        
        logger.info(f"Processing file: {uploaded_file.file_name}")
        
        # Read file based on type
        file_path = uploaded_file.file_path.path
        if uploaded_file.file_type == 'csv':
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        
        # Process rows
        valid_rows = 0
        invalid_rows = 0
        error_log = []
        messages_to_create = []
        
        for index, row in df.iterrows():
            try:
                # Clean phone number
                phone = str(row['phone']).strip()
                if not phone.startswith('+'):
                    phone = '+' + phone
                
                # Parse variables
                variables = None
                if row['has_variables'] and pd.notna(row['variables']):
                    try:
                        if isinstance(row['variables'], str):
                            variables = json.loads(row['variables'])
                        else:
                            variables = row['variables']
                    except json.JSONDecodeError:
                        variables = [v.strip() for v in str(row['variables']).split(',')]
                
                # Create message object
                message = Message(
                    campaign_id=uploaded_file.campaign_id,
                    phone_number=phone,
                    has_variables=bool(row['has_variables']),
                    variables=variables,
                    has_media=bool(row['has_media']),
                    media_url=row['media_url'] if pd.notna(row['media_url']) else None,
                    status='queued'
                )
                messages_to_create.append(message)
                valid_rows += 1
                
            except Exception as e:
                invalid_rows += 1
                error_log.append({
                    'row': index + 2,
                    'error': str(e),
                    'phone': row.get('phone', 'N/A')
                })
        
        # Bulk create messages
        if messages_to_create:
            Message.objects.bulk_create(messages_to_create, batch_size=500)
        
        # Update file status
        uploaded_file.valid_rows = valid_rows
        uploaded_file.invalid_rows = invalid_rows
        uploaded_file.row_count = len(df)
        uploaded_file.status = 'processed'
        uploaded_file.processed_at = timezone.now()
        uploaded_file.error_log = error_log if error_log else None
        uploaded_file.save()
        
        # Update campaign
        campaign = uploaded_file.campaign
        campaign.total_recipients = valid_rows
        campaign.status = 'pending' if valid_rows > 0 else 'failed'
        campaign.save()
        
        logger.info(f"File processed: {valid_rows} valid, {invalid_rows} invalid rows")
        
        return {
            'file_id': file_id,
            'valid_rows': valid_rows,
            'invalid_rows': invalid_rows
        }
        
    except Exception as e:
        logger.error(f"Error processing file {file_id}: {str(e)}")
        
        if 'uploaded_file' in locals():
            uploaded_file.status = 'failed'
            uploaded_file.error_log = {'error': str(e)}
            uploaded_file.save()
            
            campaign = uploaded_file.campaign
            campaign.status = 'failed'
            campaign.save()
        
        raise


# @shared_task
# def start_campaign_task(campaign_id):
#     """
#     Start sending messages for a campaign
#     """
#     try:
#         campaign = Campaign.objects.get(id=campaign_id)
#         logger.info(f"Starting campaign: {campaign_id}")
        
#         # Get first message to send
#         first_message = Message.objects.filter(
#             campaign_id=campaign_id,
#             status='queued'
#         ).order_by('id').first()
        
#         if first_message:
#             # Send the first message
#             send_whatsapp_message.delay(first_message.id)
#             logger.info(f"Initiated sending for campaign {campaign_id}")
#         else:
#             logger.warning(f"No queued messages found for campaign {campaign_id}")
#             campaign.status = 'completed'
#             campaign.completed_at = timezone.now()
#             campaign.save()
        
#         return {'campaign_id': campaign_id, 'status': 'started'}
        
#     except Campaign.DoesNotExist:
#         logger.error(f"Campaign {campaign_id} not found")
#         raise

@shared_task
def start_campaign_task(campaign_id):
    """
    Start sending messages for a campaign
    Modified to send all messages without waiting for webhook confirmations
    """
    from .models import Campaign, Message
    
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        logger.info(f"Starting campaign: {campaign_id}")
        
        # Get all queued messages
        messages = Message.objects.filter(
            campaign_id=campaign_id,
            status='queued'
        ).order_by('id')
        
        logger.info(f"Found {messages.count()} messages to send")
        
        # Send all messages with delay between them
        for i, message in enumerate(messages):
            # Add delay between messages (2 seconds)
            delay = i * 2
            send_whatsapp_message.apply_async(
                args=[message.id],
                countdown=delay
            )
            logger.info(f"Scheduled message {message.id} with {delay}s delay")
        
        if messages.count() == 0:
            logger.warning(f"No queued messages found for campaign {campaign_id}")
            campaign.status = 'completed'
            campaign.completed_at = timezone.now()
            campaign.save()
        else:
            # Schedule a task to check completion after all messages should be sent
            # Delay = (number of messages * 2 seconds) + 30 second buffer
            completion_delay = (messages.count() * 2) + 30
            check_campaign_completion.apply_async(
                args=[campaign_id],
                countdown=completion_delay
            )
            logger.info(f"Scheduled completion check in {completion_delay}s")
        
        return {'campaign_id': campaign_id, 'messages_scheduled': messages.count()}
        
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found")
        raise

@shared_task(bind=True, max_retries=3)
def send_whatsapp_message(self, message_id):
    """
    Send a single WhatsApp message using 360dialog
    """
    try:
        message = Message.objects.get(id=message_id)
        
        # Skip if already sent
        if message.status != 'queued':
            logger.info(f"Message {message_id} already processed, status: {message.status}")
            return
        
        # # Apply rate limiting
        # limiter = SimpleRateLimiter(message.campaign_id)
        # max_attempts = 5
        # attempts = 0
        
        # while not limiter.can_send() and attempts < max_attempts:
        #     wait_time = limiter.get_wait_time()
        #     logger.info(f"Rate limited for campaign {message.campaign_id}, waiting {wait_time} seconds...")
        #     time.sleep(wait_time)
        #     attempts += 1
        
        # if attempts >= max_attempts:
        #     logger.warning(f"Rate limit exceeded for message {message_id}, will retry later")
        #     raise self.retry(countdown=30)

        # Simple rate limiting - wait 1 second between messages
        time.sleep(1)
        
        # Update status to sending
        message.status = 'sending'
        message.save()
        
        # Initialize WhatsApp client
        client = WhatsApp360Client()
        
        # Build template components
        components = None
        if message.has_variables or message.has_media:
            components = client.build_template_components(
                body_params=message.variables if message.has_variables else None,
                media_url=message.media_url if message.has_media else None,
                media_type='image'  # Default to image, can be made dynamic
            )
        
        # Send the message
        logger.info(f"Sending message to {message.phone_number}")
        result = client.send_template_message(
            phone_number=message.phone_number,
            template_name=message.campaign.template_name,
            language_code='en',  # Can be made configurable
            components=components
        )
        print("send_whatsapp_message result:", result)
        if result['success']:
            # Message sent successfully
            message.message_id = result['message_id']
            message.status = 'sent'
            message.sent_at = timezone.now()
            message.response_code = 200
            message.response_json = result['response']
            message.save()
            
            # Update campaign counter
            Campaign.objects.filter(id=message.campaign_id).update(
                sent_count=models.F('sent_count') + 1
            )
            
            logger.info(f"Message sent successfully to {message.phone_number}, Message ID: {result['message_id']}")
            
            # Check if campaign should be completed
            check_campaign_completion.delay(message.campaign_id)
            
        else:
            # Failed to send
            message.status = 'failed'
            message.failed_at = timezone.now()
            message.error_message = result.get('error', 'Unknown error')
            message.response_code = result.get('status_code', 500)
            message.response_json = result
            message.retry_count += 1
            message.save()
            
            # Don't increment failed_count here - let webhook processor handle it
            # when we receive actual failure confirmation from WhatsApp
            
            # Retry if under max retries
            if message.retry_count < 3:
                logger.info(f"Retrying message {message_id}, attempt {message.retry_count}")
                raise self.retry(countdown=60 * message.retry_count)  # Exponential backoff
            else:
                # Max retries reached, check campaign completion
                logger.error(f"Max retries reached for message {message_id}")
                check_campaign_completion.delay(message.campaign_id)
        
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found")
    except Exception as e:
        logger.error(f"Error sending message {message_id}: {str(e)}")
        # Retry the task
        raise self.retry(exc=e, countdown=60)


@shared_task
def check_campaign_completion(campaign_id):
    """
    Check if campaign should be marked as completed
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        
        # Only check if campaign is still running
        if campaign.status != 'running':
            logger.info(f"Campaign {campaign_id} is not running, status: {campaign.status}")
            return
        
        # Check for any pending messages (queued or sending)
        pending_messages = Message.objects.filter(
            campaign_id=campaign_id,
            status__in=['queued', 'sending']
        ).count()
        
        if pending_messages == 0:
            # All messages processed, mark campaign as completed
            campaign.status = 'completed'
            campaign.completed_at = timezone.now()
            campaign.save()
            logger.info(f"Campaign {campaign_id} marked as completed - all messages sent")
        else:
            logger.info(f"Campaign {campaign_id} still has {pending_messages} pending messages")
            # Schedule another check in 30 seconds if there are still pending messages
            check_campaign_completion.apply_async(
                args=[campaign_id],
                countdown=30
            )
        
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found")
    except Exception as e:
        logger.error(f"Error checking campaign completion {campaign_id}: {str(e)}")


@shared_task
def check_all_running_campaigns():
    """
    Periodic task to check all running campaigns for completion
    This ensures no campaigns get stuck in running state
    """
    from .models import Campaign
    
    running_campaigns = Campaign.objects.filter(status='running')
    logger.info(f"Checking {running_campaigns.count()} running campaigns for completion")
    
    for campaign in running_campaigns:
        check_campaign_completion.delay(campaign.id)
        logger.info(f"Queued completion check for campaign {campaign.id}")
    
    return {'campaigns_checked': running_campaigns.count()}


@shared_task
def send_next_message(campaign_id):
    """
    Send the next queued message in the campaign
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        
        # Check if campaign is still running
        if campaign.status != 'running':
            logger.info(f"Campaign {campaign_id} is not running, status: {campaign.status}")
            return
        
        # Get next queued message
        next_message = Message.objects.filter(
            campaign_id=campaign_id,
            status='queued'
        ).order_by('id').first()
        
        if next_message:
            # Send the next message
            logger.info(f"Sending next message in campaign {campaign_id}")
            send_whatsapp_message.delay(next_message.id)
        else:
            # No more messages, check if campaign is complete
            pending_messages = Message.objects.filter(
                campaign_id=campaign_id,
                status__in=['queued', 'sending']
            ).count()
            
            if pending_messages == 0:
                # All messages processed, mark campaign as completed
                campaign.status = 'completed'
                campaign.completed_at = timezone.now()
                campaign.save()
                logger.info(f"Campaign {campaign_id} completed")
            else:
                logger.info(f"Campaign {campaign_id} has {pending_messages} pending messages")
        
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found")
    except Exception as e:
        logger.error(f"Error sending next message for campaign {campaign_id}: {str(e)}")


@shared_task
def process_webhook_status(webhook_log_id):
    """
    Process webhook status update from 360dialog
    """
    try:
        webhook_log = WebhookLog.objects.get(id=webhook_log_id)

        # Process the webhook payload
        success = process_360dialog_webhook(webhook_log.raw_payload)

        # Mark as processed
        webhook_log.processed = True
        webhook_log.processed_at = timezone.now()
        webhook_log.save()

        return {'webhook_id': webhook_log_id, 'success': success}

    except WebhookLog.DoesNotExist:
        logger.error(f"Webhook log {webhook_log_id} not found")
    except Exception as e:
        logger.error(f"Error processing webhook {webhook_log_id}: {str(e)}")


@shared_task
def process_unified_webhook_status(webhook_log_id):
    """
    Process webhook using unified router for campaigns, orders, and payments
    """
    try:
        webhook_log = WebhookLog.objects.get(id=webhook_log_id)

        # Use unified router to process webhook
        from unified_webhook_router import route_unified_webhook

        result = route_unified_webhook(webhook_log.raw_payload)

        # Mark as processed
        webhook_log.processed = True
        webhook_log.processed_at = timezone.now()
        webhook_log.save()

        logger.info(f"Webhook {webhook_log_id} processed using {result.get('processor_used')}")

        return {
            'webhook_id': webhook_log_id,
            'success': result.get('success', False),
            'processor_used': result.get('processor_used'),
            'webhook_type': result.get('webhook_type')
        }

    except WebhookLog.DoesNotExist:
        logger.error(f"Webhook log {webhook_log_id} not found")
    except Exception as e:
        logger.error(f"Error processing unified webhook {webhook_log_id}: {str(e)}")
