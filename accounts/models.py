# accounts/models.py

from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    """
    Custom User model with role-based authentication
    """
    ROLE_CHOICES = [
        ('manufacturer', 'Manufacturer'),
        ('buyer', 'Buyer'),
        ('admin', 'Admin'),          # ← ADDED
    ]
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        blank=True,                  # ← allows is_staff superusers to have no role
        default='',
        help_text="User role: manufacturer, buyer, or admin"
    )
    phone_number    = models.CharField(max_length=15, blank=True, null=True)
    company_name    = models.CharField(max_length=255, blank=True, null=True)
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
        help_text="User profile picture"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.username} - {self.get_role()}"

    def get_role(self):
        """
        Always returns a reliable role string.
        Superusers / staff who have no role set are treated as admin.
        """
        if self.role == 'admin' or self.is_staff or self.is_superuser:
            return 'admin'
        return self.role

    class Meta:
        ordering = ['-created_at']