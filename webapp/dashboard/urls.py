from django.urls import path
from . import views

urlpatterns = [
    path('', views.today_dashboard, name='today_dashboard'),
]