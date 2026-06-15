"""
Accounts App - Views
"""
from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from django.contrib.auth import login

from .models import User, StudentProfile, StudentPreference, ActivityLog
from .serializers import (
    LoginSerializer, UserSerializer, StudentProfileSerializer,
    OnboardingSerializer, StudentPreferenceSerializer, ActivityLogSerializer,
)


class LoginView(APIView):
    """Email/password login — returns JWT tokens."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        refresh = RefreshToken.for_user(user)
        
        # Log activity
        ActivityLog.objects.create(
            user=user,
            action='login',
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            device=request.data.get('device', ''),
        )

        response = Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
            'onboarding_completed': getattr(
                user, 'student_profile', None
            ) and user.student_profile.onboarding_completed or False,
        })

        # Set refresh token as httpOnly cookie
        response.set_cookie(
            'refresh_token',
            str(refresh),
            httponly=True,
            samesite='Lax',
            secure=request.is_secure(),
            max_age=7 * 24 * 60 * 60,  # 7 days
        )

        return response

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')


class LogoutView(APIView):
    """Invalidate refresh token."""

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh') or request.COOKIES.get('refresh_token')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            ActivityLog.objects.create(
                user=request.user,
                action='logout',
            )

            response = Response({'detail': 'Logged out successfully.'})
            response.delete_cookie('refresh_token')
            return response
        except Exception:
            return Response({'detail': 'Logged out.'}, status=status.HTTP_200_OK)


class ProfileView(generics.RetrieveUpdateAPIView):
    """Get or update student profile."""
    serializer_class = StudentProfileSerializer

    def get_object(self):
        profile, _ = StudentProfile.objects.get_or_create(user=self.request.user)
        return profile


class OnboardingView(APIView):
    """Complete student onboarding."""

    def post(self, request):
        profile, _ = StudentProfile.objects.get_or_create(user=request.user)
        serializer = OnboardingSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            StudentProfileSerializer(profile).data,
            status=status.HTTP_200_OK,
        )


class PreferenceView(generics.RetrieveUpdateAPIView):
    """Get or update student preferences."""
    serializer_class = StudentPreferenceSerializer

    def get_object(self):
        prefs, _ = StudentPreference.objects.get_or_create(user=self.request.user)
        return prefs


class ActivityLogListView(generics.ListAPIView):
    """List recent activity logs."""
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        return ActivityLog.objects.filter(user=self.request.user)[:50]


class GoogleLoginView(APIView):
    """Handle Google OAuth login."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # Google token validation happens via allauth
        # This endpoint is a wrapper that returns JWT tokens
        from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
        from dj_rest_auth.registration.views import SocialLoginView

        # Delegate to dj-rest-auth's social login
        return SocialLoginView.as_view(adapter_class=GoogleOAuth2Adapter)(request._request)
