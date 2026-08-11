from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone
from .rbac import Role


class User(models.Model):
    """Internal application users - Administrators and Staffing Users.

    Deliberately NOT django.contrib.auth's AUTH_USER_MODEL - this is a plain
    model authenticated via CustomJWTAuthentication (see api/authentication.py).
    is_authenticated/is_anonymous are provided so DRF's IsAuthenticated
    permission (which reads request.user.is_authenticated) works against it.
    """
    is_authenticated = True
    is_anonymous = False

    user_id = models.BigAutoField(primary_key=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField(max_length=150, unique=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    password_hash = models.CharField(max_length=255)
    role = models.ForeignKey(Role, on_delete=models.PROTECT,
                             db_column='role_id', null=False)
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL,
                                   null=True, blank=True, db_column='created_by')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Tokens issued before this timestamp are treated as stale "
                  "(see api/authentication.py and api/services/tokens.py).",
    )

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email'], name='ux_users_email'),
            models.Index(fields=['role'], name='ix_users_role_id'),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)
        self.password_changed_at = timezone.now()

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)


class OTPVerification(models.Model):
    """OTP for password reset and verification."""
    class Purpose(models.TextChoices):
        PASSWORD_RESET = 'PASSWORD_RESET', 'Password Reset'

    otp_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             db_column='user_id')
    otp_code_hash = models.CharField(max_length=255)
    purpose = models.CharField(max_length=20,
                               choices=Purpose.choices,
                               default=Purpose.PASSWORD_RESET)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'otp_verifications'
        indexes = [
            models.Index(fields=['user', 'purpose', 'expires_at'],
                        name='ix_otp_user_purpose'),
        ]

    def __str__(self):
        return f"OTP for {self.user.email} - {self.purpose}"

    def is_valid(self):
        return not self.verified_at and timezone.now() < self.expires_at