from rest_framework import serializers
from accounts.models import User
from .models import Message

class ChatUserSerializer(serializers.ModelSerializer):
    """Reuses your existing User model — no duplication"""
    profile_picture = serializers.SerializerMethodField()

    def get_profile_picture(self, obj):
        request = self.context.get('request')
        if obj.profile_picture:
            return request.build_absolute_uri(obj.profile_picture.url) if request else None
        return None

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'company_name', 'profile_picture']


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    def get_sender_name(self, obj):
        return f"{obj.sender.first_name} {obj.sender.last_name}".strip() or obj.sender.username

    class Meta:
        model = Message
        fields = ['id', 'sender', 'sender_name', 'receiver', 'message', 'is_read', 'created_at']