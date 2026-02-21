from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from accounts.models import User
from .models import Message
from .serializers import ChatUserSerializer, MessageSerializer


class ChatUsersView(APIView):
    """
    GET /api/chat/users/?role=manufacturer
    Returns all users of the opposite role to chat with.
    Buyers pass role=manufacturer, Manufacturers pass role=buyer.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.query_params.get('role', '')
        if role not in ['buyer', 'manufacturer']:
            return Response({'error': 'Invalid role. Must be buyer or manufacturer.'}, status=400)

        users = User.objects.filter(role=role).exclude(id=request.user.id)
        serializer = ChatUserSerializer(users, many=True, context={'request': request})
        return Response(serializer.data)


class MessagesView(APIView):
    """
    GET  /api/chat/messages/?receiver_id=5  → fetch conversation
    POST /api/chat/messages/                → send message
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        receiver_id = request.query_params.get('receiver_id')
        if not receiver_id:
            return Response({'error': 'receiver_id is required.'}, status=400)

        messages = Message.objects.filter(
            Q(sender=request.user, receiver_id=receiver_id) |
            Q(sender_id=receiver_id, receiver=request.user)
        )
        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request):
        receiver_id = request.data.get('receiver_id')
        message_text = request.data.get('message', '').strip()

        if not receiver_id:
            return Response({'error': 'receiver_id is required.'}, status=400)
        if not message_text:
            return Response({'error': 'message cannot be empty.'}, status=400)

        try:
            receiver = User.objects.get(id=receiver_id)
        except User.DoesNotExist:
            return Response({'error': 'Receiver not found.'}, status=404)

        msg = Message.objects.create(
            sender=request.user,
            receiver=receiver,
            message=message_text
        )
        return Response(MessageSerializer(msg).data, status=201)


class UnreadCountView(APIView):
    """GET /api/chat/unread-count/ → { count: N }"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Message.objects.filter(receiver=request.user, is_read=False).count()
        return Response({'count': count})


class MarkReadView(APIView):
    """POST /api/chat/mark-read/ → marks all messages from sender as read"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sender_id = request.data.get('sender_id')
        if not sender_id:
            return Response({'error': 'sender_id is required.'}, status=400)

        Message.objects.filter(
            sender_id=sender_id,
            receiver=request.user,
            is_read=False
        ).update(is_read=True)

        return Response({'status': 'ok'})