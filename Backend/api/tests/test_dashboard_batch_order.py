"""Batches Overview orders by how much attention a batch still wants, not by date alone.

Sorting by date alone interleaves finished batches with live ones, so the rows a TA can still
act on get scattered down a list they have to read all of. Only visible under "All" now - the
default Active view holds In Progress alone, which is what TestActiveMeansInProgressOnly below
pins down.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Batch
from api.serializers.dashboard import build_dashboard_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def batches_by_status(admin_user, make_batch):
    """One batch per status, created oldest-first in the order given.

    Dates are staggered so a date-only sort would produce a KNOWN wrong answer - without that,
    a test could pass on insertion order and prove nothing.
    """
    def _make(*statuses):
        now = timezone.now()
        created = {}
        for offset, status in enumerate(statuses):
            batch = make_batch(
                admin_user, status=status,
                batch_name=f'{status}-batch',
                created_at=now - timedelta(days=len(statuses) - offset),
            )
            created[status] = batch
        return created
    return _make


def _names(user, status_group='active'):
    return [row['batch_name']
            for row in build_dashboard_summary(user, batch_status=status_group)['batches_overview']]


class TestCompletedBatchesSinkBelowLiveOnes:
    def test_completed_comes_after_in_progress_even_when_newer(
        self, admin_user, batches_by_status,
    ):
        """The reported case: a completed batch created today must not sit above an in-progress
        one from last week. Asserted under "All", the only view that now shows both.
        """
        batches_by_status(Batch.Status.IN_PROGRESS, Batch.Status.COMPLETED)

        assert _names(admin_user, 'all') == ['in_progress-batch', 'completed-batch']

    def test_cancelled_sinks_below_completed(self, admin_user, batches_by_status):
        batches_by_status(
            Batch.Status.CANCELLED, Batch.Status.COMPLETED, Batch.Status.IN_PROGRESS,
        )

        assert _names(admin_user, 'all') == [
            'in_progress-batch', 'completed-batch', 'cancelled-batch',
        ]

    def test_drafts_rank_as_live_work(self, admin_user, batches_by_status):
        """A draft is unfinished, so it is something still to do - it belongs with In Progress
        rather than below the finished batches.
        """
        batches_by_status(Batch.Status.COMPLETED, Batch.Status.DRAFT)

        assert _names(admin_user, 'all') == ['draft-batch', 'completed-batch']

    def test_newest_first_still_holds_inside_each_band(self, admin_user, make_batch):
        now = timezone.now()
        for index, name in enumerate(['older', 'newer']):
            make_batch(admin_user, status=Batch.Status.IN_PROGRESS, batch_name=name,
                       created_at=now - timedelta(days=5 - index))

        assert _names(admin_user) == ['newer', 'older']

    def test_a_single_status_group_is_just_newest_first(self, admin_user, make_batch):
        """Nothing changes for the Draft or Cancelled tabs - every row ranks the same there."""
        now = timezone.now()
        for index, name in enumerate(['draft-old', 'draft-new']):
            make_batch(admin_user, status=Batch.Status.DRAFT, batch_name=name,
                       created_at=now - timedelta(days=5 - index))

        assert _names(admin_user, 'draft') == ['draft-new', 'draft-old']


class TestActiveMeansInProgressOnly:
    """"Active" is In Progress and nothing else, in the count AND in the table.

    Completed used to be folded in here, which left the "Active Batches" card reporting one
    number while the table directly beneath it listed a longer set - the card has always
    counted In Progress alone. Reported by a tester as "the Active Batches section includes
    completed batches".
    """

    def test_completed_is_not_in_the_default_view(self, admin_user, batches_by_status):
        batches_by_status(Batch.Status.IN_PROGRESS, Batch.Status.COMPLETED)

        assert _names(admin_user) == ['in_progress-batch']

    def test_completed_has_its_own_group(self, admin_user, batches_by_status):
        """Excluded from the default view, not hidden - one filter click away."""
        batches_by_status(Batch.Status.IN_PROGRESS, Batch.Status.COMPLETED)

        assert _names(admin_user, 'completed') == ['completed-batch']

    def test_the_card_and_the_table_agree(self, admin_user, batches_by_status):
        """The actual bug: one number above a list that contradicted it."""
        batches_by_status(
            Batch.Status.IN_PROGRESS, Batch.Status.COMPLETED, Batch.Status.CANCELLED,
        )

        summary = build_dashboard_summary(admin_user, batch_status='active')

        assert summary['stats']['active_batches'] == len(summary['batches_overview']) == 1
