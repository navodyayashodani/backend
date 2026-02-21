from django.urls import path
from . import views

urlpatterns = [
    path('users/',        views.ChatUsersView.as_view()),
    path('messages/',     views.MessagesView.as_view()),
    path('unread-count/', views.UnreadCountView.as_view()),
    path('mark-read/',    views.MarkReadView.as_view()),
]