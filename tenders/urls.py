# tenders/urls.py

from django.urls import path
from .views import (
    AcceptBidView, TenderListCreateView, TenderDetailView, NextTenderNumberView,
    PredictQualityView, TenderBidListCreateView, TenderBidDetailView,
    TenderBidsView, BatchPredictQualityView  # NEW
)

urlpatterns = [
    # Tender endpoints
    path('tenders/', TenderListCreateView.as_view(), name='tender-list-create'),
    path('tenders/<int:pk>/', TenderDetailView.as_view(), name='tender-detail'),
    path('tenders/next-number/', NextTenderNumberView.as_view(), name='next-tender-number'),
    path('tenders/predict-quality/', PredictQualityView.as_view(), name='predict-quality'),
    path('tenders/predict-quality-batch/', BatchPredictQualityView.as_view(), name='predict-quality-batch'),  # NEW
    path('tenders/<int:tender_id>/bids/', TenderBidsView.as_view(), name='tender-bids'),
    
    # Bid endpoints
    path('bids/', TenderBidListCreateView.as_view(), name='bid-list-create'),
    path('bids/<int:pk>/', TenderBidDetailView.as_view(), name='bid-detail'),
    path('bids/<int:bid_id>/accept/', AcceptBidView.as_view(), name='accept-bid'),
]