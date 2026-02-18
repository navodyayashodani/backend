# accounts/serializers.py

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User

class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration
    """
    password = serializers.CharField(
        write_only=True, 
        required=True, 
        validators=[validate_password],
        style={'input_type': 'password'},
        min_length=8,
        error_messages={
            'min_length': 'Password must be at least 8 characters long.',
            'required': 'Password is required.',
        }
    )
    password2 = serializers.CharField(
        write_only=True, 
        required=True,
        style={'input_type': 'password'},
        error_messages={'required': 'Please confirm your password.'}
    )
    email = serializers.EmailField(
        required=True,
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Please enter a valid email address.',
        }
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=15,
        min_length=10,
        error_messages={
            'min_length': 'Phone number must be at least 10 digits.',
            'max_length': 'Phone number cannot exceed 15 digits.',
        }
    )
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'password2', 
                  'role', 'phone_number', 'company_name', 'first_name', 'last_name']
        extra_kwargs = {
            'first_name': {
                'required': True,
                'error_messages': {'required': 'First name is required.'}
            },
            'last_name': {
                'required': True,
                'error_messages': {'required': 'Last name is required.'}
            },
            'username': {
                'error_messages': {
                    'required': 'Username is required.',
                    'unique': 'This username is already taken.',
                }
            },
        }
    
    def validate_username(self, value):
        """Validate username"""
        if len(value) < 3:
            raise serializers.ValidationError("Username must be at least 3 characters long.")
        if not value.isalnum() and '_' not in value:
            raise serializers.ValidationError("Username can only contain letters, numbers, and underscores.")
        return value
    
    def validate_email(self, value):
        """Validate email uniqueness"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value
    
    def validate_phone_number(self, value):
        """Validate phone number format"""
        if value:
            cleaned = value.replace(' ', '').replace('-', '').replace('+', '')
            if not cleaned.isdigit():
                raise serializers.ValidationError("Phone number must contain only digits.")
            if len(cleaned) < 10:
                raise serializers.ValidationError("Phone number must be at least 10 digits.")
        return value
    
    def validate(self, attrs):
        """Validate that passwords match"""
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({
                "password2": "Passwords do not match."
            })
        return attrs
    
    def create(self, validated_data):
        """Create new user with encrypted password"""
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user details (read-only)"""
    profile_picture = serializers.ImageField(read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 
                  'role', 'phone_number', 'company_name', 'profile_picture', 'created_at']
        read_only_fields = ['id', 'username', 'role', 'created_at']


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating user profile
    Supports both text fields and image upload
    """
    email = serializers.EmailField(required=False)
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=15,
        min_length=10,
        error_messages={
            'min_length': 'Phone number must be at least 10 digits.',
            'max_length': 'Phone number cannot exceed 15 digits.',
        }
    )
    profile_picture = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'company_name', 'profile_picture']
        extra_kwargs = {
            'first_name': {'required': False},
            'last_name': {'required': False},
            'company_name': {'required': False, 'allow_blank': True},
        }
    
    def validate_email(self, value):
        """Validate email uniqueness (exclude current user)"""
        user = self.context['request'].user
        if User.objects.filter(email=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value
    
    def validate_phone_number(self, value):
        """Validate phone number format"""
        if value:
            cleaned = value.replace(' ', '').replace('-', '').replace('+', '')
            if not cleaned.isdigit():
                raise serializers.ValidationError("Phone number must contain only digits.")
            if len(cleaned) < 10:
                raise serializers.ValidationError("Phone number must be at least 10 digits.")
        return value
    
    def validate_profile_picture(self, value):
        """Validate profile picture"""
        if value:
            # Check file size (max 1GB)
            if value.size > 1024 * 1024 * 1024:
                raise serializers.ValidationError("Image file size cannot exceed 1GB.")
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError("Only JPG, PNG, and WebP images are allowed.")
        
        return value


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    username = serializers.CharField(
        required=True,
        error_messages={'required': 'Username is required.'}
    )
    password = serializers.CharField(
        required=True, 
        write_only=True,
        style={'input_type': 'password'},
        error_messages={'required': 'Password is required.'}
    )