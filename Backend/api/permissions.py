from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Grants access only to Administrator accounts."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role.role_code == 'admin')


class IsAdminOrTA(BasePermission):
    """Grants access to either internal role (Administrator or Staffing User)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.role.role_code in ('admin', 'ta')
        )
