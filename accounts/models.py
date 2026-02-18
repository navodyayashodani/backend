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
    ]
    
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        help_text="User role: manufacturer or buyer"
    )
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    company_name = models.CharField(max_length=255, blank=True, null=True)
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
        help_text="User profile picture"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.username} - {self.role}"
    
    class Meta:
        ordering = ['-created_at']