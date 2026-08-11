from datetime import datetime

from django.http import JsonResponse


def health_check(request):
    return JsonResponse({
        'status': 'ok',
        'message': 'Backend is running!',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
    })
