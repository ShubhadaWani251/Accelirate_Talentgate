"""A new account reads as Invited until its holder actually sets it up, and an administrator
cannot switch their own account off.

Two tester reports:
  - "A newly created user appears as Active before accepting the invitation or completing
    activation." It was rendering the raw is_active boolean, which is True from the moment the
    row is written - Add User mails a generated password, and the account can do nothing at all
    until that is replaced (must_change_password, enforced in api/permissions.py).
  - "An administrator may be able to deactivate their own account." The API always refused;
    the User Management list offered the control anyway, on every row including your own.
"""
import pytest

from api.models import AuditLog, User
from api.serializers.users import account_status

pytestmark = pytest.mark.django_db


class TestDerivedAccountStatus:
    def test_a_freshly_provisioned_account_is_invited(self, admin_user, client_for):
        response = client_for(admin_user).post('/api/users/', {
            'first_name': 'Priya', 'last_name': 'Nair',
            'email': 'priya.nair@accelirate.com', 'role': 'ta',
        }, format='json')

        assert response.status_code == 201
        assert response.data['status'] == 'invited'
        assert response.data['status_display'] == 'Invited'
        # Still genuinely active - Invited is a reading of the account, not a third is_active.
        assert response.data['is_active'] is True

    def test_setting_their_own_password_makes_them_active(self, make_user):
        user = make_user(must_change_password=True)
        assert account_status(user) == ('invited', 'Invited')

        user.set_password('TheirOwnPassw0rd!')

        assert account_status(user) == ('active', 'Active')

    def test_deactivated_beats_invited(self, make_user):
        """An account switched off before it was ever set up is Inactive, not Invited -
        the invitation stopped mattering the moment the account was disabled."""
        user = make_user(must_change_password=True)
        user.is_active = False

        assert account_status(user) == ('inactive', 'Inactive')

    def test_the_list_carries_the_same_status_as_the_detail_view(self, admin_user, make_user,
                                                                 client_for):
        invited = make_user(must_change_password=True)
        client = client_for(admin_user)

        listed = {row['user_id']: row for row in client.get('/api/users/').data['results']}
        detail = client.get(f'/api/users/{invited.user_id}/').data

        assert listed[invited.user_id]['status'] == detail['status'] == 'invited'


class TestAdminCannotDeactivateThemselves:
    def test_the_deactivate_endpoint_refuses(self, admin_user, client_for):
        response = client_for(admin_user).delete(f'/api/users/{admin_user.user_id}/')

        assert response.status_code == 400
        assert 'own account' in response.data['detail']
        admin_user.refresh_from_db()
        assert admin_user.is_active is True

    def test_the_active_toggle_refuses_too(self, admin_user, client_for):
        """The other route to the same thing - PATCH is_active=false on yourself."""
        response = client_for(admin_user).patch(
            f'/api/users/{admin_user.user_id}/', {'is_active': False}, format='json',
        )

        assert response.status_code == 400
        admin_user.refresh_from_db()
        assert admin_user.is_active is True

    def test_editing_your_own_name_still_works(self, admin_user, client_for):
        """The guard is about deactivation alone - it must not lock an admin out of their
        own record entirely."""
        response = client_for(admin_user).patch(
            f'/api/users/{admin_user.user_id}/', {'first_name': 'Renamed'}, format='json',
        )

        assert response.status_code == 200
        admin_user.refresh_from_db()
        assert admin_user.first_name == 'Renamed'

    def test_another_admin_may_deactivate_an_admin(self, admin_user, make_user, client_for):
        """Explicitly allowed by the same report - it is only SELF-deactivation that is barred."""
        colleague = make_user(role='admin', email='second.admin@accelirate.com')

        response = client_for(admin_user).delete(f'/api/users/{colleague.user_id}/')

        assert response.status_code == 200
        colleague.refresh_from_db()
        assert colleague.is_active is False

    def test_the_last_administrator_cannot_be_removed(self, admin_user, make_user, client_for):
        """Falls out of the rule above rather than being enforced separately: whoever performs
        the final deactivation is, by definition, not the one being deactivated."""
        colleague = make_user(role='admin', email='second.admin@accelirate.com')
        client_for(admin_user).delete(f'/api/users/{colleague.user_id}/')

        client_for(admin_user).delete(f'/api/users/{admin_user.user_id}/')

        assert User.objects.filter(role__role_code='admin', is_active=True,
                                   is_deleted=False).exists()


class TestSignInOnADeactivatedAccountIsLogged:
    """It used to record nothing at all - see views/auth.LoginView. The one attempt an
    administrator would most want to find afterwards was the only one left out of the log.
    """

    def test_a_blocked_sign_in_writes_an_audit_row(self, make_user, api_client):
        user = make_user(email='gone@accelirate.com')
        user.is_active = False
        user.set_password('CorrectHorse1!')
        user.save()

        response = api_client.post('/api/auth/login/', {
            'email': 'gone@accelirate.com', 'password': 'CorrectHorse1!',
        }, format='json')

        assert response.status_code == 401
        assert AuditLog.objects.filter(user=user, action_type='login_blocked').exists()

    def test_a_wrong_password_on_a_live_account_still_says_login_failed(self, make_user,
                                                                        api_client):
        user = make_user(email='live@accelirate.com')
        user.set_password('CorrectHorse1!')
        user.save()

        api_client.post('/api/auth/login/', {
            'email': 'live@accelirate.com', 'password': 'wrong',
        }, format='json')

        assert AuditLog.objects.filter(user=user, action_type='login_failed').exists()
        assert not AuditLog.objects.filter(user=user, action_type='login_blocked').exists()
