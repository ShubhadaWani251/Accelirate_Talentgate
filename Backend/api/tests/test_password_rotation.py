"""Forced rotation of handover passwords.

Account provisioning mails a generated password in plain text, and `manage.py
reset_user_password` has an admin type one in. Either way the password is known to someone other
than the account holder and lives on in a mailbox or a terminal, so it is a handover credential.
Before this, nothing made anyone replace one - the provisioning email only asked politely, and a
temp password stayed a fully-privileged credential for as long as the account existed.

The gate is server-side (api/permissions.py) rather than a frontend redirect, so these tests
drive the HTTP surface: what a pending account can and cannot reach, and what clears it.
"""
import pytest
from django.utils import timezone

from api.models import OTPVerification, User
from api.permissions import PASSWORD_CHANGE_REQUIRED_MESSAGE
from api.services import user_provisioning

pytestmark = pytest.mark.django_db

CURRENT_PASSWORD = 'HandedOver#1'
NEW_PASSWORD = 'ChosenByMe#99'


@pytest.fixture
def pending_user(make_user):
    """A TA still on the password somebody else issued them."""
    user = make_user(role='ta', email='pending@accelirate.com')
    user.set_password(CURRENT_PASSWORD)
    user.must_change_password = True
    user.save()
    return user


class TestProvisioningMarksTheAccount:
    def test_a_newly_provisioned_user_must_change_their_password(self, roles, admin_user, settings):
        settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

        user = user_provisioning.create_user_with_credentials(
            {'first_name': 'New', 'last_name': 'Starter',
             'email': 'new.starter@accelirate.com', 'role': roles['ta']},
            created_by=admin_user,
        )

        assert User.objects.get(pk=user.pk).must_change_password is True

    def test_an_ordinary_account_is_not_marked(self, ta_user):
        assert ta_user.must_change_password is False


class TestAPendingAccountCannotUseTheApplication:
    def test_a_staff_endpoint_is_refused(self, pending_user, client_for):
        response = client_for(pending_user).get('/api/candidates/')

        assert response.status_code == 403

    def test_the_refusal_says_what_to_do_about_it(self, pending_user, client_for):
        """A bare "you do not have permission" reads as a role problem and sends people to an
        administrator, when the fix is entirely in their own hands.
        """
        response = client_for(pending_user).get('/api/candidates/')

        assert response.data['detail'] == PASSWORD_CHANGE_REQUIRED_MESSAGE

    def test_an_admin_only_endpoint_is_refused_too(self, make_user, client_for):
        admin = make_user(role='admin', email='pending.admin@accelirate.com')
        admin.set_password(CURRENT_PASSWORD)
        admin.must_change_password = True
        admin.save()

        assert client_for(admin).get('/api/users/').status_code == 403

    def test_they_can_still_read_their_own_profile(self, pending_user, client_for):
        """/api/auth/me/ is how the frontend learns it needs to redirect, so closing it would
        make the state undiscoverable to the client.
        """
        response = client_for(pending_user).get('/api/auth/me/')

        assert response.status_code == 200
        assert response.data['must_change_password'] is True

    def test_they_can_still_log_out(self, pending_user, client_for):
        assert client_for(pending_user).post('/api/auth/logout/').status_code == 200


class TestChangingThePasswordRestoresAccess:
    def test_the_change_password_endpoint_is_reachable(self, pending_user, client_for):
        response = client_for(pending_user).post('/api/auth/change-password/', {
            'current_password': CURRENT_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })

        assert response.status_code == 200

    def test_the_flag_is_cleared_in_the_database(self, pending_user, client_for):
        """set_password() clears it, but the view saves with update_fields - so this is really
        asserting that 'must_change_password' is in that list. Leave it out and the clear is
        silently dropped and the user is stuck forever.
        """
        client_for(pending_user).post('/api/auth/change-password/', {
            'current_password': CURRENT_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })

        pending_user.refresh_from_db()
        assert pending_user.must_change_password is False

    def test_staff_endpoints_work_again_afterwards(self, pending_user, api_client):
        """Driven through the tokens the change-password response itself returns, because it
        reissues them - the old ones are deliberately invalidated by the password change.
        """
        client = api_client
        from api.services.tokens import issue_tokens_for_user
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_tokens_for_user(pending_user)[1])
        changed = client.post('/api/auth/change-password/', {
            'current_password': CURRENT_PASSWORD,
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + changed.data['access_token'])

        assert client.get('/api/candidates/').status_code == 200

    def test_a_self_service_otp_reset_also_clears_it(self, pending_user, api_client):
        """The forgot-password route has to clear the flag too - someone who never remembers the
        mailed password and resets it instead has still chosen their own, and would otherwise be
        locked out of the whole application with no way back.
        """
        from django.contrib.auth.hashers import make_password
        OTPVerification.objects.create(
            user=pending_user, otp_code_hash=make_password('123456'),
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )

        response = api_client.post('/api/auth/verify-otp/', {
            'email': pending_user.email, 'otp': '123456',
            'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD,
        })

        assert response.status_code == 200, response.data
        pending_user.refresh_from_db()
        assert pending_user.must_change_password is False


class TestLoginTellsTheClient:
    def test_the_login_response_carries_the_flag(self, pending_user, api_client):
        response = api_client.post('/api/auth/login/', {
            'email': pending_user.email, 'password': CURRENT_PASSWORD,
        })

        assert response.status_code == 200, response.data
        assert response.data['user']['must_change_password'] is True

    def test_an_ordinary_login_reports_false(self, ta_user, api_client):
        ta_user.set_password(CURRENT_PASSWORD)
        ta_user.save()

        response = api_client.post('/api/auth/login/', {
            'email': ta_user.email, 'password': CURRENT_PASSWORD,
        })

        assert response.data['user']['must_change_password'] is False
