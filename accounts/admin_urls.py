# accounts/admin_urls.py

from django.urls import path
from . import admin_views

urlpatterns = [
    path('stats/',                 admin_views.AdminStatsView.as_view()),
    path('users/',                 admin_views.AdminUserListView.as_view()),
    path('users/<int:pk>/',        admin_views.AdminUserDetailView.as_view()),
    path('tenders/',               admin_views.AdminTenderListView.as_view()),
    path('tenders/<int:pk>/',      admin_views.AdminTenderDetailView.as_view()),
    path('bids/',                  admin_views.AdminBidListView.as_view()),
    path('grading-reports/',       admin_views.AdminGradingReportListView.as_view()),
    path('activity-logs/',         admin_views.AdminActivityLogListView.as_view()),
    path('reports/summary/',       admin_views.AdminSummaryReportView.as_view()),
]