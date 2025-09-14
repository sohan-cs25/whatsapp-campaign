from django.shortcuts import render

# Create your views here.

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from .serializers import (
    SignupSerializer, 
    LoginSerializer, 
    UserSerializer,
    ChangePasswordSerializer
)
import logging

logger = logging.getLogger(__name__)


class SignupView(APIView):
    """User registration endpoint"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """
        Create a new user account
        
        Request body:
        {
            "username": "string",
            "email": "email",
            "password": "string",
            "password2": "string",
            "first_name": "string",  // optional
            "last_name": "string"    // optional
        }
        """
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            
            # Create token for the user
            token, created = Token.objects.get_or_create(user=user)
            
            # Log the signup
            logger.info(f"New user registered: {user.username}")
            
            return Response({
                'success': True,
                'message': 'User created successfully',
                'user': UserSerializer(user).data,
                'token': token.key
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """User login endpoint"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        """
        Login user and return token
        
        Request body:
        {
            "username": "string",  // or email
            "password": "string"
        }
        """
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            
            # Login the user
            login(request, user)
            
            # Get or create token
            token, created = Token.objects.get_or_create(user=user)
            
            # Update last login
            user.save()
            
            logger.info(f"User logged in: {user.username}")
            
            return Response({
                'success': True,
                'message': 'Login successful',
                'user': UserSerializer(user).data,
                'token': token.key
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    """User logout endpoint"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Logout user and delete token
        """
        try:
            # Delete the user's token
            request.user.auth_token.delete()
            
            # Logout
            logout(request)
            
            logger.info(f"User logged out: {request.user.username}")
            
            return Response({
                'success': True,
                'message': 'Logout successful'
            }, status=status.HTTP_200_OK)
        except:
            # Even if token doesn't exist, logout the user
            logout(request)
            
            return Response({
                'success': True,
                'message': 'Logout successful'
            }, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """Get and update user profile"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get current user details
        """
        serializer = UserSerializer(request.user)
        return Response({
            'success': True,
            'user': serializer.data
        }, status=status.HTTP_200_OK)
    
    def put(self, request):
        """
        Update user profile
        
        Request body:
        {
            "first_name": "string",
            "last_name": "string",
            "email": "email"
        }
        """
        serializer = UserSerializer(
            request.user, 
            data=request.data, 
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save()
            
            logger.info(f"User profile updated: {request.user.username}")
            
            return Response({
                'success': True,
                'message': 'Profile updated successfully',
                'user': serializer.data
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class ChangePasswordView(APIView):
    """Change user password"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Change user password
        
        Request body:
        {
            "old_password": "string",
            "new_password": "string",
            "new_password2": "string"
        }
        """
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        
        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            
            # Delete old token and create new one
            try:
                request.user.auth_token.delete()
            except:
                pass
            
            token, created = Token.objects.get_or_create(user=user)
            
            logger.info(f"Password changed for user: {user.username}")
            
            return Response({
                'success': True,
                'message': 'Password changed successfully',
                'token': token.key
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verify_token(request):
    """
    Verify if token is valid
    """
    return Response({
        'success': True,
        'valid': True,
        'user': UserSerializer(request.user).data
    }, status=status.HTTP_200_OK)
