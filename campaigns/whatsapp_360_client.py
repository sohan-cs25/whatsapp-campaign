# campaigns/whatsapp_360_client.py

import requests
import json
import logging
from typing import Dict, List, Optional, Any
from decouple import config
from django.conf import settings
import time

logger = logging.getLogger(__name__)


class WhatsApp360Client:
    """Client for 360dialog WhatsApp Business API"""
    
    def __init__(self):
        self.api_key = config('WHATSAPP_360_API_KEY')
        self.api_url = config('WHATSAPP_360_API_URL', default='https://waba-v2.360dialog.io')
        self.session = requests.Session()
        self.session.headers.update({
            'D360-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        })
    
    def send_template_message(
        self,
        phone_number: str,
        template_name: str,
        language_code: str = 'en',
        components: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Send a WhatsApp template message via 360dialog
        
        Args:
            phone_number: Recipient's phone number (with country code, no +)
            template_name: Name of the approved template
            language_code: Language code for the template (default: 'en')
            components: Template components (header, body parameters)
        
        Returns:
            dict: API response containing message ID and status
        """
        # Remove + from phone number if present
        phone_number = phone_number.replace('+', '')
        
        # Build the payload
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            },
            "message_activity_sharing": True
        }
        print(payload)
        # Add components if provided
        if components:
            payload["template"]["components"] = components
        
        # Make the API request
        endpoint = f"{self.api_url}/marketing_messages"
        
        try:
            logger.info(f"Sending WhatsApp message to {phone_number} using template {template_name}")
            
            response = self.session.post(
                endpoint,
                json=payload,
                timeout=30
            )
            
            response_data = response.json()
            print(response_data)
            
            if response.status_code == 200 or response.status_code == 201:
                logger.info(f"Message sent successfully. Message ID: {response_data.get('messages', [{}])[0].get('id')}")
                return {
                    'success': True,
                    'message_id': response_data.get('messages', [{}])[0].get('id'),
                    'response': response_data
                }
            else:
                logger.error(f"Failed to send message. Status: {response.status_code}, Response: {response_data}")
                return {
                    'success': False,
                    'error': response_data.get('error', {}).get('message', 'Unknown error'),
                    'status_code': response.status_code,
                    'response': response_data
                }
                
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout while sending message to {phone_number}")
            return {
                'success': False,
                'error': 'Request timeout',
                'status_code': 408
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'status_code': 500
            }
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'status_code': 500
            }

    def send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a WhatsApp message with custom payload (for order_details template)

        Args:
            payload: Complete WhatsApp API payload

        Returns:
            dict: API response containing message ID and status
        """
        try:
            logger.info(f"Sending WhatsApp message to {payload.get('to')}")

            response = self.session.post(
                f"{self.api_url}/messages",
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Message sent successfully: {result}")
                return {
                    'success': True,
                    'message_id': result.get('messages', [{}])[0].get('id'),
                    'response': result,
                    'status_code': 200
                }
            else:
                logger.error(f"Failed to send message: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': response.text,
                    'status_code': response.status_code
                }

        except requests.exceptions.Timeout:
            logger.error("Request timeout while sending message")
            return {
                'success': False,
                'error': 'Request timeout',
                'status_code': 408
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'status_code': 500
            }
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'status_code': 500
            }

    def build_template_components(
        self,
        header_params: Optional[List] = None,
        body_params: Optional[List] = None,
        button_params: Optional[List] = None,
        media_url: Optional[str] = None,
        media_type: str = 'image'
    ) -> List[Dict]:
        """
        Build template components for 360dialog API
        
        Args:
            header_params: Parameters for header component
            body_params: Parameters for body component (variables)
            button_params: Parameters for button component
            media_url: URL of media to include in header
            media_type: Type of media (image, video, document)
        
        Returns:
            list: List of component dictionaries
        """
        components = []
        
        # Add header component if media or header params
        if media_url:
            components.append({
                "type": "header",
                "parameters": [{
                    "type": media_type,
                    media_type: {
                        "link": media_url
                    }
                }]
            })
        elif header_params:
            header_component = {
                "type": "header",
                "parameters": []
            }
            for param in header_params:
                header_component["parameters"].append({
                    "type": "text",
                    "text": str(param)
                })
            components.append(header_component)
        
        # Add body component if variables present
        if body_params:
            body_component = {
                "type": "body",
                "parameters": []
            }
            for param in body_params:
                body_component["parameters"].append({
                    "type": "text",
                    "text": str(param)
                })
            components.append(body_component)
        
        # Add button component if parameters present
        if button_params:
            for i, param in enumerate(button_params):
                components.append({
                    "type": "button",
                    "sub_type": "url",
                    "index": str(i),
                    "parameters": [{
                        "type": "text",
                        "text": str(param)
                    }]
                })
        
        return components if components else None
    
    def validate_phone_number(self, phone_number: str) -> bool:
        """
        Basic validation of phone number format
        
        Args:
            phone_number: Phone number to validate
        
        Returns:
            bool: True if valid format
        """
        import re
        # Remove + and spaces
        cleaned = phone_number.replace('+', '').replace(' ', '').replace('-', '')
        # Check if it's all digits and has reasonable length (7-15 digits)
        return bool(re.match(r'^\d{7,15}$', cleaned))
    
    def format_phone_number(self, phone_number: str) -> str:
        """
        Format phone number for 360dialog API (remove + sign)
        
        Args:
            phone_number: Phone number to format
        
        Returns:
            str: Formatted phone number
        """
        return phone_number.replace('+', '').replace(' ', '').replace('-', '')


class WhatsApp360Error(Exception):
    """Custom exception for 360dialog API errors"""
    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data