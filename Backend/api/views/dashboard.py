from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import IsAdminOrTA
from api.serializers.dashboard import build_dashboard_summary


class DashboardSummaryView(APIView):
    permission_classes = [IsAdminOrTA]

    def get(self, request):
        return Response(build_dashboard_summary(request.user))
