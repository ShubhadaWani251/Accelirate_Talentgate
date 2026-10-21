"""The Audit Log's date filter covers the same day the screen's own column shows.

Reported as "today's login activity is not visible in Audit Log history". The rows were always
written - login has been logged since the first commit. The filter read From/To as UTC dates
while the table renders each timestamp in the reader's own zone (Asia/Kolkata, +5:30), so
anything logged between midnight and 05:30 local carried the PREVIOUS day's UTC date and fell
outside a filter for the very day it was displayed under.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings

from api.models import AuditLog

pytestmark = pytest.mark.django_db

IST = ZoneInfo('Asia/Kolkata')


@pytest.fixture
def display_tz_is_ist(settings):
    settings.DISPLAY_TIME_ZONE = 'Asia/Kolkata'
    return settings.DISPLAY_TIME_ZONE


def _login_at(user, local_dt):
    """One sign-in row, stamped at a wall-clock time in the DISPLAY timezone."""
    log = AuditLog.objects.create(
        user=user, action_type='login', entity_type='user', entity_id=user.user_id,
    )
    # created_at is auto-populated; overwrite it without touching anything else.
    AuditLog.objects.filter(pk=log.pk).update(created_at=local_dt.replace(tzinfo=IST))
    return AuditLog.objects.get(pk=log.pk)


def _logs_between(client, date_from=None, date_to=None):
    params = {}
    if date_from:
        params['date_from'] = date_from
    if date_to:
        params['date_to'] = date_to
    response = client.get('/api/audit-logs/', params)
    assert response.status_code == 200
    return [row['log_id'] for row in response.data['results']]


class TestEarlyMorningActivityIsNotLost:
    def test_a_login_just_after_local_midnight_is_in_that_days_filter(
        self, admin_user, client_for, display_tz_is_ist,
    ):
        """02:00 IST on the 16th is 20:30 UTC on the 15th - the exact row that vanished."""
        log = _login_at(admin_user, datetime(2026, 10, 16, 2, 0))

        assert log.log_id in _logs_between(client_for(admin_user), date_from='2026-10-16')

    def test_the_same_login_is_excluded_from_the_previous_day(
        self, admin_user, client_for, display_tz_is_ist,
    ):
        """The other half of the fix: it must not leak backwards into the 15th either."""
        log = _login_at(admin_user, datetime(2026, 10, 16, 2, 0))

        listed = _logs_between(client_for(admin_user),
                               date_from='2026-10-15', date_to='2026-10-15')

        assert log.log_id not in listed

    def test_late_evening_local_time_is_still_the_same_day(
        self, admin_user, client_for, display_tz_is_ist,
    ):
        log = _login_at(admin_user, datetime(2026, 10, 16, 23, 30))

        listed = _logs_between(client_for(admin_user),
                               date_from='2026-10-16', date_to='2026-10-16')

        assert log.log_id in listed

    def test_a_single_day_filter_spans_exactly_that_local_day(
        self, admin_user, client_for, display_tz_is_ist,
    ):
        """Both local-midnight edges at once - 00:05 in, 23:55 the day before out."""
        just_inside = _login_at(admin_user, datetime(2026, 10, 16, 0, 5))
        just_before = _login_at(admin_user, datetime(2026, 10, 15, 23, 55))

        listed = _logs_between(client_for(admin_user),
                               date_from='2026-10-16', date_to='2026-10-16')

        assert just_inside.log_id in listed
        assert just_before.log_id not in listed

    def test_an_unparseable_date_narrows_nothing(self, admin_user, client_for):
        log = _login_at(admin_user, datetime(2026, 10, 16, 2, 0))

        assert log.log_id in _logs_between(client_for(admin_user), date_from='not-a-date')
