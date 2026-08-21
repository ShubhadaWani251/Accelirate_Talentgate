from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Registers the deployment system checks in api/checks.py. Importing here rather than
        # at module scope is the documented way to do this - at import time the app registry
        # isn't populated yet, so anything the checks touch may not exist.
        from . import checks  # noqa: F401
