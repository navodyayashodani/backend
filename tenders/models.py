# tenders/models.py

from django.db import models
from django.core.validators import MinValueValidator, FileExtensionValidator
from accounts.models import User
import os

def tender_report_path(instance, filename):
    """Generate file path for tender reports"""
    return f'tender_reports/{instance.tender_number}/{filename}'

class Tender(models.Model):
    """
    Tender model for cinnamon oil tenders
    """
    OIL_TYPE_CHOICES = [
        ('crude', 'Crude Cinnamon Oil'),
        ('refined', 'Refined Cinnamon Oil'),
        ('organic', 'Organic Cinnamon Oil'),
        ('conventional', 'Conventional Cinnamon Oil'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('awarded', 'Awarded'),
    ]
    
    # Auto-generated tender number
    tender_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        help_text="Auto-generated tender number"
    )
    
    # Manufacturer who created the tender
    manufacturer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tenders',
        limit_choices_to={'role': 'manufacturer'}
    )
    
    # Tender basic information
    tender_title = models.CharField(
        max_length=255,
        help_text="Title/name of the tender"
    )
    
    oil_type = models.CharField(
        max_length=50,
        choices=OIL_TYPE_CHOICES,
        help_text="Type of cinnamon oil"
    )
    
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text="Quantity in liters or kg"
    )
    
    quality_grade = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Quality grade (A+, A, B, C, etc.) - Auto-generated from ML model"
    )
    
    quality_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Quality score from ML model (0-100)"
    )
    
    tender_description = models.TextField(
        help_text="Detailed description of the tender"
    )
    
    # Report upload
    report_file = models.FileField(
        upload_to=tender_report_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=['pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg']
            )
        ],
        help_text="Upload oil quality report (PDF, DOC, XLS, or Image)"
    )
    
    # Dates
    start_date = models.DateField(
        help_text="Tender start date"
    )
    
    end_date = models.DateField(
        help_text="Tender end date"
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Tender'
        verbose_name_plural = 'Tenders'
    
    def __str__(self):
        return f"{self.tender_number} - {self.tender_title}"
    
    def save(self, *args, **kwargs):
        """Override save to generate tender number"""
        if not self.tender_number:
            # Get the last tender number
            last_tender = Tender.objects.all().order_by('-id').first()
            if last_tender and last_tender.tender_number:
                # Extract number from format TND-001
                try:
                    last_number = int(last_tender.tender_number.split('-')[1])
                    new_number = last_number + 1
                except (IndexError, ValueError):
                    new_number = 1
            else:
                new_number = 1
            
            # Format: TND-001, TND-002, etc.
            self.tender_number = f"TND-{new_number:03d}"
        
        super().save(*args, **kwargs)
    
    @property
    def is_active(self):
        """Check if tender is currently active"""
        from django.utils import timezone
        today = timezone.now().date()
        return self.status == 'active' and self.start_date <= today <= self.end_date


class TenderBid(models.Model):
    """
    Bids placed by buyers on tenders
    """
    tender = models.ForeignKey(
        Tender,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    
    buyer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='bids',
        limit_choices_to={'role': 'buyer'}
    )
    
    bid_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text="Bid amount per unit"
    )
    
    message = models.TextField(
        blank=True,
        help_text="Optional message to manufacturer"
    )
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('accepted', 'Accepted'),
            ('rejected', 'Rejected'),
        ],
        default='pending'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['tender', 'buyer']
    
    def __str__(self):
        return f"Bid by {self.buyer.username} on {self.tender.tender_number}"