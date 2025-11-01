from django.urls import path
from .views import DevAnalystView

urlpatterns = [
    path('api/dev-analyst/', DevAnalystView.as_view(), name='dev_analyst_api'),
]
