"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

# The Django admin is deliberately not routed here, and django.contrib.admin is not installed
# (see INSTALLED_APPS in settings.py for the full reasoning). Short version: it registered every
# model with no write protection, against a different user table than the one this app
# authenticates with, so it was a complete bypass of the app's own role checks - including an
# editable AuditLog and readable Question.correct_option. Staff administration lives in the app's
# own User Management screen, which enforces the real permissions.
urlpatterns = [
    path('api/', include('api.urls')),
]

if settings.DEBUG:
    # Serves the local-disk evidence fallback (api/services/blob_storage.py) when no Azure
    # connection string is configured - never active in production.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)