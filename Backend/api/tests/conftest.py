"""Shared test fixtures: object factories and cache isolation."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient


# Settings overrides that keep this suite away from real infrastructure live in
# config/settings_test.py, which pytest.ini selects as DJANGO_SETTINGS_MODULE. They are NOT done
# here: by the time any conftest hook runs, pytest-django has already initialised Django and the
# connection handler has cached the database settings, so overriding DATABASES from a conftest
# changed ENGINE but left the test database name derived from the real one - i.e. it would still
# have created a database on the production-adjacent server.


@pytest.fixture(autouse=True)
def clear_cache():
    """Empty the cache around every test.

    Rate limiting counts per key in the default cache. Without this the first test to hit a
    limited endpoint leaves counters behind and a later test gets an unexpected 429 - the classic
    passes-alone, fails-in-suite failure.
    """
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------- model factories
# Plain functions rather than factory_boy: that library was pinned for years without ever being
# imported, and these few helpers do not justify re-adding the dependency.

@pytest.fixture
def roles(db):
    from api.models import Role
    return {
        'admin': Role.objects.create(role_name='Administrator', role_code='admin', priority=1),
        'ta': Role.objects.create(role_name='Staffing User', role_code='ta', priority=2),
    }


@pytest.fixture
def make_user(db, roles):
    from api.models import User
    counter = {'n': 0}

    def _make(role='ta', email=None, **kwargs):
        counter['n'] += 1
        n = counter['n']
        return User.objects.create(
            first_name='User%d' % n,
            last_name='Test',
            email=email or 'user%d@accelirate.com' % n,
            role=roles[role],
            is_active=True,
            **kwargs
        )
    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user(role='admin', email='admin@accelirate.com')


@pytest.fixture
def ta_user(make_user):
    return make_user(role='ta', email='ta1@accelirate.com')


@pytest.fixture
def other_ta_user(make_user):
    return make_user(role='ta', email='ta2@accelirate.com')


@pytest.fixture
def make_batch(db):
    from api.models import Batch
    counter = {'n': 0}

    def _make(owner, status=Batch.Status.IN_PROGRESS, created_at=None, **kwargs):
        counter['n'] += 1
        now = timezone.now()
        params = dict(
            batch_name='Batch %d' % counter['n'],
            college_name='Test College',
            link_valid_from=now,
            link_valid_until=now + timedelta(days=7),
            status=status,
            primary_ta_user=owner,
            created_by=owner,
            exam_duration_minutes=45,
            logical_questions=2,
            quantitative_questions=2,
            verbal_questions=2,
            programming_questions=2,
        )
        params.update(kwargs)
        batch = Batch.objects.create(**params)
        if created_at is not None:
            # created_at is auto_now_add and cannot be passed to create(). Written straight to
            # the row afterwards, because the entire draft-expiry rule keys off this value and
            # tests need to be able to age a batch.
            Batch.objects.filter(pk=batch.pk).update(created_at=created_at)
            batch.refresh_from_db()
        return batch
    return _make


@pytest.fixture
def make_candidate(db):
    from api.models import Candidate
    counter = {'n': 0}

    def _make(batch, owner, **kwargs):
        counter['n'] += 1
        n = counter['n']
        params = dict(
            first_name='Cand%d' % n,
            last_name='Test',
            email='cand%d@example.test' % n,
            aadhaar_last4='1234',
            college_name='Test College',
            degree='BE',
            stream='CS',
            percentage=70,
            passing_out_year=2025,
            location='Pune',
            phone='9000000000',
            batch=batch,
            created_by=owner,
        )
        params.update(kwargs)
        return Candidate.objects.create(**params)
    return _make


@pytest.fixture
def make_invitation(db):
    from api.models import Invitation
    counter = {'n': 0}

    def _make(candidate, sent_by, created_at=None, **kwargs):
        counter['n'] += 1
        params = dict(
            candidate=candidate,
            batch=candidate.batch,
            unique_link_token='test-token-%d' % counter['n'],
            link_expired_at=timezone.now() + timedelta(days=2),
            sent_by=sent_by,
        )
        params.update(kwargs)
        invitation = Invitation.objects.create(**params)
        if created_at is not None:
            # Same reason as batch created_at: auto_now_add, and the retry sweep measures its
            # grace period against it.
            Invitation.objects.filter(pk=invitation.pk).update(created_at=created_at)
            invitation.refresh_from_db()
        return invitation
    return _make


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def client_for(db):
    """Builds a client authenticated as a given user, the same way a real login does."""
    from api.services.tokens import issue_tokens_for_user

    def _for(user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer ' + issue_tokens_for_user(user)[1])
        return client
    return _for
