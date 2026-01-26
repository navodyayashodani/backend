# tenders/admin.py

from django.contrib import admin
from .models import Tender, TenderBid

@admin.register(Tender)
class TenderAdmin(admin.ModelAdmin):
    list_display = ['tender_number', 'tender_title', 'manufacturer', 'oil_type', 
                    'quantity', 'quality_grade', 'status', 'created_at']
    list_filter = ['status', 'oil_type', 'created_at']
    search_fields = ['tender_number', 'tender_title', 'manufacturer__username']
    readonly_fields = ['tender_number', 'quality_grade', 'quality_score', 'created_at', 'updated_at']

@admin.register(TenderBid)
class TenderBidAdmin(admin.ModelAdmin):
    list_display = ['tender', 'buyer', 'bid_amount', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['tender__tender_number', 'buyer__username']