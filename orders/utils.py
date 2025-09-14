"""
Utility functions for orders app
Integrates chat processing tools with Django models
"""

import os
import pandas as pd
from typing import List, Dict, Optional
from django.conf import settings
from .tools.chat_parser import parse_chat_content, get_chat_statistics
from .models import ChatFile, ParsedChatFile, ValidatedFile, Order


def process_chat_file_content(chat_file: ChatFile) -> Dict:
    """
    Process a ChatFile using the chat parser

    Args:
        chat_file: ChatFile instance

    Returns:
        Dictionary containing processing results
    """
    try:
        # Read file content
        file_path = chat_file.filepath.path
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse chat content
        messages = parse_chat_content(content)
        stats = get_chat_statistics(messages)

        return {
            'success': True,
            'messages': messages,
            'stats': stats,
            'total_messages': stats['total_messages'],
            'unique_senders': stats['unique_senders'],
            'error': None
        }

    except Exception as e:
        return {
            'success': False,
            'messages': [],
            'stats': {},
            'total_messages': 0,
            'unique_senders': 0,
            'error': str(e)
        }


def save_processed_chat_to_excel(messages: List[Dict], output_path: str) -> bool:
    """
    Save processed chat messages to Excel file (basic format for initial parsing)

    Args:
        messages: List of parsed message dictionaries
        output_path: Path where to save the Excel file

    Returns:
        Boolean indicating success
    """
    try:
        # Create DataFrame
        df = pd.DataFrame(messages)

        # Add placeholder columns for AI classification
        df['Message_Type'] = ''  # order, enquiry, review, etc.
        df['Confidence'] = ''
        df['Order_Items'] = ''
        df['Order_Amount'] = ''
        df['Customer_Details'] = ''
        df['Notes'] = ''

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Save to Excel
        df.to_excel(output_path, index=False)

        return True

    except Exception as e:
        print(f"Error saving to Excel: {str(e)}")
        return False


def save_enhanced_messages_to_excel(processed_messages: List[Dict], output_path: str) -> bool:
    """
    Save AI-enhanced messages to Excel file matching sample_parsedfile_after_ai.csv format
    Expected columns: Date, Time, Phone/Name, Message, Message_Type, Items, Total_Amount

    Args:
        processed_messages: List of AI-processed message dictionaries
        output_path: Path where to save the Excel file

    Returns:
        Boolean indicating success
    """
    try:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Prepare data matching exact sample format
        excel_data = []

        for msg in processed_messages:
            row = {
                'Date': msg.get('Date', ''),
                'Time': msg.get('Time', ''),
                'Phone/Name': msg.get('Phone/Name', ''),
                'Message': msg.get('Message', ''),
                'Message_Type': msg.get('Message_Type', ''),
                'Items': msg.get('Items', ''),  # AI-extracted items in simple format
                'Total_Amount': msg.get('Total_Amount', '')  # AI-extracted amount
            }
            excel_data.append(row)

        # Create DataFrame with exact column order from sample
        df = pd.DataFrame(excel_data)

        # Ensure columns are in the exact order from sample file
        column_order = ['Date', 'Time', 'Phone/Name', 'Message', 'Message_Type', 'Items', 'Total_Amount']
        df = df.reindex(columns=column_order, fill_value='')

        # Save to Excel
        df.to_excel(output_path, index=False, engine='openpyxl')

        print(f"Enhanced messages saved to: {output_path}")
        return True

    except Exception as e:
        print(f"Error saving enhanced messages to Excel: {str(e)}")
        return False


def create_parsed_chat_file(chat_file: ChatFile, messages: List[Dict], stats: Dict) -> ParsedChatFile:
    """
    Create a ParsedChatFile record from processed messages

    Args:
        chat_file: Original ChatFile instance
        messages: Parsed message data
        stats: Chat statistics

    Returns:
        ParsedChatFile instance
    """
    # Generate output filename
    base_name = os.path.splitext(chat_file.filename)[0]
    output_filename = f"{base_name}_processed.xlsx"

    # Create output path in processedchatfile directory
    output_path = os.path.join(
        settings.ORDERS_MEDIA_ROOT,
        'processedchatfile',
        output_filename
    )

    # Save messages to Excel
    success = save_processed_chat_to_excel(messages, output_path)

    if not success:
        raise Exception("Failed to save processed file")

    # Create ParsedChatFile record
    parsed_file = ParsedChatFile.objects.create(
        user=chat_file.user,
        chatfile=chat_file,
        file_name=output_filename,
        processed_file_path=f"processedchatfile/{output_filename}",
        total_messages=stats.get('total_messages', 0),
        total_orders=0,  # Will be updated after AI classification
        total_queries=0,  # Will be updated after AI classification
    )

    # Mark original chat file as processed
    chat_file.is_processed = True
    chat_file.processed_at = parsed_file.processed_at
    chat_file.save()

    return parsed_file


def validate_upload_file_format(file_path: str, expected_columns: List[str] = None) -> Dict:
    """
    Validate uploaded file format for validated files

    Args:
        file_path: Path to the uploaded file
        expected_columns: List of expected column names

    Returns:
        Dictionary with validation results
    """
    if expected_columns is None:
        expected_columns = [
            'Date', 'Time', 'Phone/Name', 'Message', 'Message_Type',
            'Order_Items', 'Order_Amount', 'Customer_Details'
        ]

    try:
        # Read file
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            return {
                'valid': False,
                'error': 'Unsupported file format. Use .xlsx or .csv',
                'row_count': 0,
                'missing_columns': []
            }

        # Check columns
        missing_columns = [col for col in expected_columns if col not in df.columns]

        # Check for order data
        order_rows = df[df['Message_Type'].str.lower() == 'order'] if 'Message_Type' in df.columns else pd.DataFrame()

        return {
            'valid': len(missing_columns) == 0,
            'error': f"Missing columns: {missing_columns}" if missing_columns else None,
            'row_count': len(df),
            'order_count': len(order_rows),
            'missing_columns': missing_columns,
            'dataframe': df if len(missing_columns) == 0 else None
        }

    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'row_count': 0,
            'order_count': 0,
            'missing_columns': []
        }


def extract_orders_from_validated_file(validated_file: ValidatedFile) -> List[Order]:
    """
    Extract Order instances from a ValidatedFile

    Args:
        validated_file: ValidatedFile instance

    Returns:
        List of created Order instances
    """
    try:
        # Read the validated file
        file_path = validated_file.filepath.path
        validation_result = validate_upload_file_format(file_path)

        if not validation_result['valid']:
            raise Exception(f"Invalid file format: {validation_result['error']}")

        df = validation_result['dataframe']

        # Filter for order messages
        order_df = df[df['Message_Type'].str.lower() == 'order'].copy()

        created_orders = []

        for _, row in order_df.iterrows():
            # Parse order data
            phone_number = str(row.get('Phone/Name', '')).strip()
            order_items_str = str(row.get('Order_Items', '')).strip()
            order_amount_str = str(row.get('Order_Amount', '')).strip()

            # Skip if essential data is missing
            if not phone_number or not order_items_str:
                continue

            try:
                # Parse order items (assume JSON or comma-separated format)
                if order_items_str.startswith('{') or order_items_str.startswith('['):
                    order_items = eval(order_items_str)  # Use json.loads in production
                else:
                    # Simple comma-separated format
                    items = [item.strip() for item in order_items_str.split(',')]
                    order_items = {f"item_{i+1}": item for i, item in enumerate(items)}

                # Parse amount
                order_amount = 0.0
                if order_amount_str and order_amount_str.replace('.', '').replace(',', '').isdigit():
                    order_amount = float(order_amount_str.replace(',', ''))

                # Create Order instance
                order = Order.objects.create(
                    validated_file=validated_file,
                    number=phone_number,
                    order_items=order_items,
                    amount=order_amount,
                    status='pending'
                )

                created_orders.append(order)

            except Exception as e:
                print(f"Error processing order row: {str(e)}")
                continue

        # Update ValidatedFile statistics
        validated_file.is_processed = True
        validated_file.orders_extracted = len(created_orders)
        validated_file.save()

        return created_orders

    except Exception as e:
        raise Exception(f"Failed to extract orders: {str(e)}")


def get_file_processing_status(user, file_type: str = 'all') -> Dict:
    """
    Get processing status for user's files

    Args:
        user: User instance
        file_type: 'chat', 'processed', 'validated', or 'all'

    Returns:
        Dictionary with file counts and status
    """
    status = {}

    if file_type in ['chat', 'all']:
        chat_files = ChatFile.objects.filter(user=user)
        status['chat_files'] = {
            'total': chat_files.count(),
            'processed': chat_files.filter(is_processed=True).count(),
            'pending': chat_files.filter(is_processed=False).count()
        }

    if file_type in ['processed', 'all']:
        processed_files = ParsedChatFile.objects.filter(user=user)
        status['processed_files'] = {
            'total': processed_files.count(),
            'downloaded': processed_files.filter(downloaded_at__isnull=False).count(),
            'not_downloaded': processed_files.filter(downloaded_at__isnull=True).count()
        }

    if file_type in ['validated', 'all']:
        validated_files = ValidatedFile.objects.filter(user=user)
        status['validated_files'] = {
            'total': validated_files.count(),
            'processed': validated_files.filter(is_processed=True).count(),
            'pending': validated_files.filter(is_processed=False).count()
        }

        # Order statistics
        orders = Order.objects.filter(validated_file__user=user)
        status['orders'] = {
            'total': orders.count(),
            'pending': orders.filter(status='pending').count(),
            'sent': orders.filter(status__in=['sent', 'delivered', 'read']).count(),
            'failed': orders.filter(status='failed').count()
        }

    return status


# Helper function to clean phone numbers
def clean_phone_number(phone: str) -> str:
    """
    Clean and format phone number

    Args:
        phone: Raw phone number string

    Returns:
        Cleaned phone number
    """
    if not phone:
        return ""

    # Remove all non-digit characters except +
    cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')

    # Add + if not present and number starts with country code
    if not cleaned.startswith('+') and len(cleaned) > 10:
        cleaned = '+' + cleaned

    return cleaned


# Helper function to validate order amount
def parse_order_amount(amount_str: str) -> float:
    """
    Parse order amount from string

    Args:
        amount_str: Amount string (can include currency symbols, commas)

    Returns:
        Float amount value
    """
    if not amount_str:
        return 0.0

    # Remove currency symbols and commas
    cleaned = ''.join(c for c in amount_str if c.isdigit() or c == '.')

    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0