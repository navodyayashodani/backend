from django.db import models
from django.conf import settings

class Message(models.Model):
    sender   = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_messages',     on_delete=models.CASCADE)
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='received_messages', on_delete=models.CASCADE)
    message  = models.TextField()
    is_read  = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username} → {self.receiver.username}: {self.message[:40]}"