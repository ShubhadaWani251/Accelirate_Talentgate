from rest_framework.permissions import BasePermission

# Shown to a staff user whose account is still on a handover password. Deliberately specific:
# a generic 403 here looks like a role problem and sends people to an administrator, when the
# fix is entirely in their own hands.
PASSWORD_CHANGE_REQUIRED_MESSAGE = (
    'Set your own password before using the application. The password you signed in with was '
    'issued to you by someone else. Open Profile to change it.'
)


def password_change_pending(user):
    """Whether this account is still using a password somebody else chose for it.

    getattr rather than a bare attribute read: the same permission classes are evaluated
    against request.user on candidate exam endpoints, where `user` is an ExamAttempt (see
    api/authentication.CandidateAttemptAuthentication), not a User.
    """
    return bool(getattr(user, 'must_change_password', False))


class StaffPermission(BasePermission):
    """Base for the staff role checks below.

    Every staff data endpoint in this app declares IsAdmin or IsAdminOrTA, so gating both here
    covers the whole authenticated surface in one place, without touching the deliberately bare
    `IsAuthenticated` views: Logout, ChangePassword and Me (which a user on a handover password
    still has to reach in order to fix it) and the candidate exam endpoints (a different
    authentication class and a different kind of principal entirely).
    """
    #: Role codes this permission admits. Subclasses set it.
    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if password_change_pending(user):
            # Set on the instance, not the class: DRF builds a fresh permission object per
            # request (APIView.get_permissions), so this can't leak the wrong reason into
            # another request. Without it a pending password change would surface as the
            # generic "you do not have permission" and read as a role problem.
            self.message = PASSWORD_CHANGE_REQUIRED_MESSAGE
            return False
        return user.role.role_code in self.allowed_roles


class IsAdmin(StaffPermission):
    """Grants access only to Administrator accounts."""
    allowed_roles = ('admin',)


class IsAdminOrTA(StaffPermission):
    """Grants access to either internal role (Administrator or Staffing User)."""
    allowed_roles = ('admin', 'ta')
