"""
Celery tasks for orders app
Handles asynchronous processing of chat files and order extraction
"""

from celery import shared_task
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
import logging
from datetime import timedelta
import os

from .models import ChatFile, ParsedChatFile, ValidatedFile, Order
from .utils import (
    process_chat_file_content,
    create_parsed_chat_file,
    extract_orders_from_validated_file,
    save_enhanced_messages_to_excel
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_chat_file(self, chat_file_id):
    """
    Complete processing: Basic parsing + AI classification in one task
    Produces final file matching sample_parsedfile_after_ai.csv format

    Args:
        chat_file_id: UUID of the ChatFile to process

    Returns:
        Dictionary with processing results
    """
    from .ai_service import django_ai_service
    from .tools.chat_parser import parse_chat_content

    try:
        # Get chat file
        chat_file = ChatFile.objects.get(id=chat_file_id)

        logger.info(f"Starting complete processing of chat file: {chat_file.filename}")

        # Clear any previous errors
        chat_file.processing_error = ""
        chat_file.save()

        # Step 1: Basic Chat Parsing
        logger.info("Step 1: Basic chat parsing...")
        file_path = chat_file.filepath.path
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        messages = parse_chat_content(content)

        if not messages:
            raise Exception("No messages found in chat file")

        logger.info(f"Parsed {len(messages)} messages")

        # Step 2: AI Classification with rate limiting
        logger.info("Step 2: AI classification (this may take time due to rate limits)...")

        # Use the new synchronous wrapper that handles async/sync compatibility
        processed_messages, stats, run_result = django_ai_service.process_chat_messages_sync(
            messages=messages,
            chat_file_id=str(chat_file.id)
        )

        logger.info(f"AI classification completed. Found {stats.orders_found} orders")

        # Step 3: Save final processed file
        base_name = os.path.splitext(chat_file.filename)[0]
        output_filename = f"{base_name}_processed.xlsx"

        # Create output path
        from django.conf import settings
        output_path = os.path.join(
            settings.ORDERS_MEDIA_ROOT,
            'processedchatfile',
            output_filename
        )

        # Save enhanced messages to Excel with correct format
        success = save_enhanced_messages_to_excel(processed_messages, output_path)
        if not success:
            raise Exception("Failed to save processed Excel file")

        # Step 4: Create ParsedChatFile record
        # update_or_create: a retry after a later step failed must not hit the one-to-one constraint
        parsed_file, _ = ParsedChatFile.objects.update_or_create(
            chatfile=chat_file,
            defaults=dict(
                user=chat_file.user,
                file_name=output_filename,
                processed_file_path=f"processedchatfile/{output_filename}",
                total_messages=stats.total_messages,
                total_orders=stats.orders_found,
                total_queries=stats.message_types.get('enquiry', 0),
            ),
        )

        # Step 5: One priced order per customer, ready for review in the app
        from .order_builder import build_orders
        orders = build_orders(parsed_file, run_result.get("orders"))
        parsed_file.total_orders = len(orders)
        parsed_file.save(update_fields=['total_orders'])
        logger.info(f"Built {len(orders)} customer orders for review")

        # Mark original file as processed
        chat_file.is_processed = True
        chat_file.processed_at = timezone.now()
        chat_file.save()

        logger.info(f"Complete processing successful: {parsed_file.file_name}")
        logger.info(f"Final stats: {stats.total_messages} messages, {stats.orders_found} orders")

        return {
            'success': True,
            'chat_file_id': str(chat_file.id),
            'parsed_file_id': str(parsed_file.id),
            'total_messages': stats.total_messages,
            'total_orders': parsed_file.total_orders,
            'total_queries': stats.message_types.get('enquiry', 0),
            'processing_time': stats.processing_time,
            'success_rate': stats.success_rate,
            'message_types': stats.message_types,
            'output_file': output_filename
        }

    except ObjectDoesNotExist:
        error_msg = f"ChatFile with id {chat_file_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }

    except Exception as exc:
        error_msg = f"Error in complete processing {chat_file_id}: {str(exc)}"
        logger.error(error_msg)

        # Update chat file error status
        try:
            chat_file = ChatFile.objects.get(id=chat_file_id)
            chat_file.processing_error = str(exc)[:500]
            chat_file.save()
        except:
            pass

        # Retry logic with longer delays for AI processing
        if self.request.retries < self.max_retries:
            countdown = 180 * (self.request.retries + 1)  # 3, 6, 9 minutes
            logger.info(f"Retrying complete processing in {countdown} seconds (attempt {self.request.retries + 1})")
            raise self.retry(countdown=countdown, exc=exc)

        return {
            'success': False,
            'error': error_msg,
            'chat_file_id': str(chat_file_id)
        }


# Removed classify_messages_with_ai task - now integrated into process_chat_file


@shared_task(bind=True, max_retries=3)
def extract_orders_from_file(self, validated_file_id):
    """
    Extract orders from validated file

    Args:
        validated_file_id: UUID of the ValidatedFile to process

    Returns:
        Dictionary with extraction results
    """
    try:
        # Get validated file
        validated_file = ValidatedFile.objects.get(id=validated_file_id)

        logger.info(f"Starting order extraction from: {validated_file.file_name}")

        # Extract orders
        orders = extract_orders_from_validated_file(validated_file)

        logger.info(f"Successfully extracted {len(orders)} orders from: {validated_file.file_name}")

        return {
            'success': True,
            'validated_file_id': str(validated_file.id),
            'orders_extracted': len(orders),
            'order_ids': [str(order.id) for order in orders]
        }

    except ObjectDoesNotExist:
        error_msg = f"ValidatedFile with id {validated_file_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }

    except Exception as exc:
        error_msg = f"Error extracting orders from {validated_file_id}: {str(exc)}"
        logger.error(error_msg)

        # Retry logic
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying extraction in 60 seconds (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60, exc=exc)

        return {
            'success': False,
            'error': error_msg,
            'validated_file_id': str(validated_file_id)
        }


@shared_task(bind=True, max_retries=5)
def send_order_confirmation(self, order_id):
    """
    Send WhatsApp order confirmation message

    Args:
        order_id: UUID of the Order to send confirmation for

    Returns:
        Dictionary with sending results
    """
    try:
        # Get order
        order = Order.objects.get(id=order_id)

        logger.info(f"Sending order confirmation for: {order.number}")

        # Update order status
        order.status = 'sending'
        order.save()

        # TODO: Integrate with existing WhatsApp client from campaigns app
        # This would reuse the whatsapp_360_client.py functionality

        # Placeholder - simulate sending
        order.status = 'sent'
        order.sent_at = timezone.now()
        order.message_id = f"msg_{order.id}_{timezone.now().timestamp()}"
        order.response_code = 200
        order.response_json = {'status': 'sent', 'message': 'Order confirmation sent'}
        order.save()

        logger.info(f"Order confirmation sent successfully for: {order.number}")

        return {
            'success': True,
            'order_id': str(order.id),
            'message_id': order.message_id,
            'status': order.status
        }

    except ObjectDoesNotExist:
        error_msg = f"Order with id {order_id} not found"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }

    except Exception as exc:
        error_msg = f"Error sending order confirmation for {order_id}: {str(exc)}"
        logger.error(error_msg)

        # Update order status
        try:
            order = Order.objects.get(id=order_id)
            order.status = 'failed'
            order.response_json = {'error': str(exc)[:200]}
            order.save()
        except:
            pass

        # Retry logic with exponential backoff
        countdown = 2 ** self.request.retries * 60  # 60, 120, 240, 480, 960 seconds
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying order confirmation in {countdown} seconds (attempt {self.request.retries + 1})")
            raise self.retry(countdown=countdown, exc=exc)

        return {
            'success': False,
            'error': error_msg,
            'order_id': str(order_id)
        }


@shared_task
def process_webhook_event(webhook_data):
    """
    Process webhook events for order status updates

    Args:
        webhook_data: Dictionary containing webhook payload

    Returns:
        Dictionary with processing results
    """
    try:
        logger.info(f"Processing webhook event: {webhook_data.get('type', 'unknown')}")

        # TODO: Implement webhook processing logic
        # This would extend the existing webhook system from campaigns app

        return {
            'success': True,
            'processed': True
        }

    except Exception as exc:
        error_msg = f"Error processing webhook: {str(exc)}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }


@shared_task
def cleanup_old_files():
    """
    Cleanup old processed files (run periodically)

    Returns:
        Dictionary with cleanup results
    """
    try:
        from datetime import datetime, timedelta

        # Delete files older than 30 days
        cutoff_date = timezone.now() - timedelta(days=30)

        old_chat_files = ChatFile.objects.filter(
            uploaded_at__lt=cutoff_date,
            is_processed=True
        )

        old_parsed_files = ParsedChatFile.objects.filter(
            processed_at__lt=cutoff_date,
            downloaded_at__isnull=False
        )

        chat_files_deleted = old_chat_files.count()
        parsed_files_deleted = old_parsed_files.count()

        # Delete file records (files will be deleted by Django's FileField)
        old_chat_files.delete()
        old_parsed_files.delete()

        logger.info(f"Cleanup completed: {chat_files_deleted} chat files, {parsed_files_deleted} parsed files")

        return {
            'success': True,
            'chat_files_deleted': chat_files_deleted,
            'parsed_files_deleted': parsed_files_deleted
        }

    except Exception as exc:
        error_msg = f"Error during cleanup: {str(exc)}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg
        }

ORDER_SEND_GAP_SECONDS = 2


@shared_task
def send_order_batch(parsed_file_id):
    """Schedule every approved, unsent order of a processed chat file, 2 seconds apart."""
    orders = Order.objects.filter(parsed_file_id=parsed_file_id, review_status='approved',
                                  status='pending').order_by('created_at')
    ids = [str(o.id) for o in orders]
    for i, order_id in enumerate(ids):
        send_single_order.apply_async(args=[order_id], countdown=i * ORDER_SEND_GAP_SECONDS)
    logger.info(f"Scheduled {len(ids)} order messages for parsed file {parsed_file_id}")
    return {'scheduled': len(ids)}


@shared_task
def send_single_order(order_id):
    """Send one approved order. The pending -> sending claim makes duplicate tasks harmless."""
    claimed = Order.objects.filter(id=order_id, status='pending', review_status='approved').update(
        status='sending', updated_at=timezone.now())
    if not claimed:
        logger.info(f"Order {order_id} not pending+approved; skipping send")
        return 'skipped'
    from . import whatsapp_service
    order = Order.objects.get(id=order_id)
    try:
        whatsapp_service.OrderWhatsAppService().send_order_message(order)
    except Exception as e:
        logger.error(f"Sending order {order_id} failed: {e}")
        # The service marks failures itself; this covers errors raised before it got that far.
        Order.objects.filter(id=order_id, status='sending').update(
            status='failed', whatsapp_response_json={'error': str(e)}, updated_at=timezone.now())
    order.refresh_from_db()
    return order.status


STUCK_SENDING_AFTER = timedelta(minutes=15)


@shared_task
def fail_stuck_sending_orders():
    """Orders left in 'sending' (worker killed mid-send) are marked failed, not re-sent: the
    WhatsApp message may already have gone out, so a person decides whether to resend."""
    cutoff = timezone.now() - STUCK_SENDING_AFTER
    n = Order.objects.filter(status='sending', updated_at__lt=cutoff).update(
        status='failed', updated_at=timezone.now(),
        whatsapp_response_json={'error': 'Send interrupted; check WhatsApp before resending'})
    if n:
        logger.warning(f"Marked {n} orders stuck in 'sending' as failed")
    return n
