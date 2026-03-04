# accounts/views.py

from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.contrib.auth import authenticate
from .models import User
from .serializers import (
    UserRegistrationSerializer,
    UserSerializer,
    UserUpdateSerializer,
    LoginSerializer
)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        print("=" * 50)
        print("Registration request received")
        print("Data:", request.data)
        print("=" * 50)

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            print("Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        print(f"User created successfully: {user.username}")

        refresh = RefreshToken.for_user(user)

        response_data = {
            'user': UserSerializer(user, context={'request': request}).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'message': 'User registered successfully!'
        }

        print("Registration successful, sending response")
        return Response(response_data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = LoginSerializer

    def post(self, request):
        print("=" * 50)
        print("Login request received")
        print("Data:", request.data)
        print("=" * 50)

        serializer = LoginSerializer(data=request.data)

        if not serializer.is_valid():
            print("Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        print(f"Attempting to authenticate user: {username}")

        user = authenticate(username=username, password=password)

        if user is not None:
            print(f"Authentication successful for: {username}")
            print(f"  role={user.role!r}  is_staff={user.is_staff}  is_superuser={user.is_superuser}")

            refresh = RefreshToken.for_user(user)

            # Build the serialized user data
            user_data = UserSerializer(user, context={'request': request}).data

            # ── KEY FIX ──────────────────────────────────────────────────────
            # Always return a reliable 'role' field.
            # If Django created this user via `createsuperuser` or set
            # is_staff=True, they have no role in ROLE_CHOICES — override it.
            if user.is_staff or user.is_superuser or user.role == 'admin':
                user_data['role'] = 'admin'
            # ────────────────────────────────────────────────────────────────

            print(f"  Returning role: {user_data['role']}")

            response_data = {
                'user': user_data,
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'message': 'Login successful!'
            }

            return Response(response_data, status=status.HTTP_200_OK)

        else:
            print(f"Authentication failed for: {username}")

            if User.objects.filter(username=username).exists():
                return Response(
                    {'error': 'Invalid password. Please try again.'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            else:
                return Response(
                    {'error': 'User not found. Please check your username.'},
                    status=status.HTTP_401_UNAUTHORIZED
                )


class UserProfileView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class UserProfileUpdateView(generics.UpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        if not serializer.is_valid():
            print("Validation errors:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_update(serializer)
        print(f"Profile updated successfully for: {instance.username}")

        return Response({
            'user': UserSerializer(instance, context={'request': request}).data,
            'message': 'Profile updated successfully!'
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh_token")

            if not refresh_token:
                return Response(
                    {'error': 'Refresh token is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({'message': 'Logout successful!'}, status=status.HTTP_205_RESET_CONTENT)

        except Exception as e:
            print(f"Logout error: {str(e)}")
            return Response(
                {'error': 'Invalid token or token already blacklisted'},
                status=status.HTTP_400_BAD_REQUEST
            )