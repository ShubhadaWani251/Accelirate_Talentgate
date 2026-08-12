from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Batch, User
from api.pagination import StandardResultsPagination
from api.permissions import IsAdmin
from api.serializers.users import UserCreateSerializer, UserDetailSerializer, UserListSerializer, UserUpdateSerializer
from api.services.audit import log_action
from api.services.user_provisioning import create_user_with_credentials


def _get_user_or_404(user_id):
    try:
        return User.objects.select_related('role').get(user_id=user_id, is_deleted=False)
    except User.DoesNotExist:
        raise Http404


class UserListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        users = User.objects.select_related('role').filter(is_deleted=False).order_by('first_name', 'last_name')
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(users, request, view=self)
        return paginator.get_paginated_response(UserListSerializer(page, many=True).data)

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = create_user_with_credentials(serializer.validated_data, request.user)
        log_action(request, request.user, 'create', 'user', user.user_id, requires_review=True)
        return Response(UserDetailSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, user_id):
        user = _get_user_or_404(user_id)
        return Response(UserDetailSerializer(user).data)

    def patch(self, request, user_id):
        user = _get_user_or_404(user_id)
        serializer = UserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if user.user_id == request.user.user_id and 'is_active' in data and not data['is_active']:
            return Response({'detail': "You can't deactivate your own account."},
                             status=status.HTTP_400_BAD_REQUEST)

        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'role' in data:
            user.role = data['role']
        if 'is_active' in data:
            user.is_active = data['is_active']
        user.save()

        log_action(request, request.user, 'update', 'user', user.user_id, requires_review=True)
        return Response(UserDetailSerializer(user).data)

    def delete(self, request, user_id):
        user = _get_user_or_404(user_id)

        if user.user_id == request.user.user_id:
            return Response({'detail': "You can't delete your own account."},
                             status=status.HTTP_400_BAD_REQUEST)

        open_batches = user.primary_batches.filter(
            is_deleted=False, status__in=[Batch.Status.DRAFT, Batch.Status.IN_PROGRESS],
        )
        if open_batches.exists():
            batch_names = ', '.join(open_batches.values_list('batch_name', flat=True))
            return Response(
                {'detail': f'{user.full_name} still owns open batch(es) ({batch_names}). '
                            f'Finalize/complete them, or reassign, before deleting this account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Soft delete only - User.is_deleted mirrors the app's Candidate/Batch pattern, and
        # Batch.primary_ta_user is on_delete=PROTECT, so a real .delete() would fail anyway
        # once any batch (even a completed one) still references this user.
        user.is_deleted = True
        user.is_active = False
        user.save(update_fields=['is_deleted', 'is_active'])

        log_action(request, request.user, 'delete', 'user', user.user_id, requires_review=True)
        return Response({'detail': f"{user.full_name}'s access has been deactivated and removed."})
