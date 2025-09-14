
from django.urls import path
from .views import (
    SignupView,
    LoginView,
    LogoutView,
    UserProfileView,
    ChangePasswordView,
    verify_token
)

app_name = 'authentication'

urlpatterns = [
    path('signup/', SignupView.as_view(), name='signup'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('user/', UserProfileView.as_view(), name='user-profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('verify-token/', verify_token, name='verify-token'),
]