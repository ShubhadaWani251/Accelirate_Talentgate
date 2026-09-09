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
from django.urls import path, include, re_path

from . import spa

# /admin/ is only ever routed when DEBUG=True - see the INSTALLED_APPS comment in settings.py
# and api/admin.py's module docstring for the full reasoning (short version: it's a full RBAC
# bypass against a different user table, so it must never exist in a real deployment). Staff
# administration for anything user-facing still lives in the app's own User Management screen,
# which enforces the real permissions; this is a local-dev-only convenience on top of that, not
# a replacement for it.
urlpatterns = [
    path('api/', include('api.urls')),
]

# Checked via INSTALLED_APPS, not settings.DEBUG directly: settings.py only appends
# 'django.contrib.admin' to INSTALLED_APPS at IMPORT TIME, when DEBUG is whatever a real .env
# says - a test overriding settings.DEBUG later (e.g. to force blob_storage's local-disk
# fallback, see test_exam_seb.py) does not retroactively install the app, so re-deriving this
# from DEBUG a second time here would try to import an app that was never actually installed and
# crash the first request any test makes while that override is active. INSTALLED_APPS is the
# fact that was actually decided; DEBUG here would just be re-asking a question already answered.
if 'django.contrib.admin' in settings.INSTALLED_APPS:
    from django.contrib import admin
    # NOT /admin/ - the React app already owns that whole prefix for its own admin screens
    # (User Management, Question Bank, Audit Logs - see AppRouter.jsx), routed client-side via
    # the SPA catch-all below. path('admin/', admin.site.urls) here would shadow every one of
    # those (Django admin's own urlconf 404s on /admin/users etc. rather than falling through
    # to the SPA), breaking real app navigation any time DEBUG=True. django-admin/ avoids the
    # collision entirely.
    urlpatterns += [path('django-admin/', admin.site.urls)]

if settings.DEBUG:
    # Serves the local-disk evidence fallback (api/services/blob_storage.py) when no Azure
    # connection string is configured - never active in production.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# SPA catch-all, last so it can never shadow the patterns above. Every client-side route -
# including the candidate assessment links at /t/<token> - has to return index.html rather than
# a 404, because those paths exist only in the React router. The negative lookahead keeps
# unmatched /api/ paths returning a real 404 instead of quietly handing back the HTML shell,
# which would otherwise turn every API typo into a confusing parse error on the client.
urlpatterns += [re_path(r'^(?!api/).*$', spa.index, name='spa')]
