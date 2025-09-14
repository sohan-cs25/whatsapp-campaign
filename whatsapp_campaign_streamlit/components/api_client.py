
import requests
import streamlit as st
from typing import Dict, Any, Optional, List
import json
from config import API_BASE_URL

class APIClient:
    """API Client for communicating with Django backend"""
    
    def __init__(self):
        self.base_url = API_BASE_URL
        self.token = st.session_state.get('auth_token', None)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers with authentication token"""
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Token {self.token}'  # Django REST Framework token format
        return headers
    
    def _handle_response(self, response) -> Dict[str, Any]:
        """Handle API response"""
        try:
            data = response.json()
            if response.status_code >= 400:
                return {'success': False, 'error': data.get('error', 'An error occurred')}
            return data
        except json.JSONDecodeError:
            return {'success': False, 'error': 'Invalid response from server'}
    
    # Authentication APIs
    def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login user"""
        url = f"{self.base_url}/auth/login/"
        response = requests.post(url, json={
            'username': username,
            'password': password
        })
        return self._handle_response(response)
    
    def signup(self, username: str, email: str, password: str, password2: str, 
               first_name: str = "", last_name: str = "") -> Dict[str, Any]:
        """Register new user"""
        url = f"{self.base_url}/auth/signup/"
        response = requests.post(url, json={
            'username': username,
            'email': email,
            'password': password,
            'password2': password2,
            'first_name': first_name,
            'last_name': last_name
        })
        return self._handle_response(response)
    
    def logout(self) -> Dict[str, Any]:
        """Logout user"""
        url = f"{self.base_url}/auth/logout/"
        response = requests.post(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def get_user(self) -> Dict[str, Any]:
        """Get current user details"""
        url = f"{self.base_url}/auth/user/"
        response = requests.get(url, headers=self._get_headers())
        return self._handle_response(response)
    
    # Campaign APIs
    def get_campaigns(self, page: int = 1) -> Dict[str, Any]:
        """Get all campaigns with pagination"""
        url = f"{self.base_url}/campaigns/"
        params = {'page': page}
        response = requests.get(url, headers=self._get_headers(), params=params)
        return self._handle_response(response)
    
    def get_all_campaigns(self) -> Dict[str, Any]:
        """Get all campaigns by fetching all pages"""
        all_campaigns = []
        page = 1
        
        while True:
            response = self.get_campaigns(page=page)
            if response.get('results'):
                all_campaigns.extend(response['results'])
                if not response.get('next'):  # No more pages
                    break
                page += 1
            else:
                break
        
        return {
            'results': all_campaigns,
            'count': len(all_campaigns),
            'success': True
        }
    
    def get_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Get campaign details"""
        url = f"{self.base_url}/campaigns/{campaign_id}/"
        response = requests.get(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def create_campaign(self, template_name: str, file) -> Dict[str, Any]:
        """Create new campaign with file upload"""
        url = f"{self.base_url}/campaigns/"
        headers = {'Authorization': f'Token {self.token}'}
        
        files = {'file': (file.name, file, file.type)}
        data = {'template_name': template_name}
        
        response = requests.post(url, headers=headers, files=files, data=data)
        return self._handle_response(response)
    
    def start_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Start a campaign"""
        url = f"{self.base_url}/campaigns/{campaign_id}/start/"
        response = requests.post(url, headers=self._get_headers())
        print("Start campaign :",response,response.status_code, response.text)
        return self._handle_response(response)
    
    def pause_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Pause a campaign"""
        url = f"{self.base_url}/campaigns/{campaign_id}/pause/"
        response = requests.post(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def resume_campaign(self, campaign_id: int) -> Dict[str, Any]:
        """Resume a campaign"""
        url = f"{self.base_url}/campaigns/{campaign_id}/resume/"
        response = requests.post(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def check_campaign_status(self, campaign_id: int) -> Dict[str, Any]:
        """Check and update campaign status"""
        url = f"{self.base_url}/campaigns/{campaign_id}/check-status/"
        response = requests.post(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def get_campaign_statistics(self, campaign_id: int) -> Dict[str, Any]:
        """Get campaign statistics"""
        url = f"{self.base_url}/campaigns/{campaign_id}/statistics/"
        response = requests.get(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def get_campaign_messages(self, campaign_id: int, status: Optional[str] = None) -> Dict[str, Any]:
        """Get campaign messages"""
        url = f"{self.base_url}/campaigns/{campaign_id}/messages/"
        if status:
            url += f"?status={status}"
        response = requests.get(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics"""
        url = f"{self.base_url}/stats/"
        response = requests.get(url, headers=self._get_headers())
        return self._handle_response(response)
    
    def validate_file(self, file) -> Dict[str, Any]:
        """Validate CSV/Excel file"""
        url = f"{self.base_url}/validate-file/"
        headers = {'Authorization': f'Token {self.token}'}
        
        files = {'file': (file.name, file, file.type)}
        
        response = requests.post(url, headers=headers, files=files)
        return self._handle_response(response)
