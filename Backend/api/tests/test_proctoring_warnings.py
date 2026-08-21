"""The warn-then-terminate tier, and which causes belong to it.

The rule is one warning for anything a candidate can plausibly recover from, and no warning for
a deliberate keypress. The warning count is shared across all causes and counted server-side, so
a reload cannot buy another one.
"""

import pytest

from api.models import ExamAttempt, ProctoringEvent
from api.services import exam_session
from api.services.exam_session import TerminationReason


@pytest.fixture
def attempt(ta_user, make_batch, make_candidate, make_invitation):
    candidate = make_candidate(make_batch(ta_user), ta_user)
    invitation = make_invitation(candidate, ta_user)
    return ExamAttempt.objects.create(
        candidate=candidate,
        invitation=invitation,
        status=ExamAttempt.Status.IN_PROGRESS,
    )


class TestWhichCausesAreWarnable:
    @pytest.mark.parametrize('reason', [
        TerminationReason.TAB_SWITCH,
        TerminationReason.WINDOW_BLUR,
        TerminationReason.FULLSCREEN_EXIT,
        TerminationReason.CAMERA_OFF,
    ])
    def test_recoverable_causes_get_a_warning(self, reason):
        assert reason in exam_session.WARNABLE_REASONS

    @pytest.mark.parametrize('reason', [
        TerminationReason.DEVTOOLS_ATTEMPT,
        TerminationReason.VIEW_SOURCE_ATTEMPT,
        TerminationReason.SCREENSHOT_ATTEMPT,
        TerminationReason.SYSTEM_ISSUE,
    ])
    def test_deliberate_keypresses_and_dead_feeds_do_not(self, reason):
        """A devtools or Print Screen keypress is nobody's accident. system_issue means the feed
        is gone, and there is nothing a warning could ask the candidate to do about it.
        """
        assert reason not in exam_session.WARNABLE_REASONS

    def test_every_reason_has_both_messages(self):
        """A missing entry is a KeyError at the worst possible moment - mid-exam, on the path
        that ends someone's attempt.
        """
        reasons = [v for k, v in vars(TerminationReason).items() if not k.startswith('_')]
        for reason in reasons:
            assert reason in exam_session.TERMINATION_MESSAGES, reason
            assert reason in exam_session.TERMINATION_LABELS, reason

    def test_every_warnable_reason_has_a_cause_phrase(self):
        """Without one it falls back to 'the assessment window was left', which for a camera
        being switched off would be simply untrue.
        """
        for reason in exam_session.WARNABLE_REASONS:
            assert reason in exam_session._WARNING_CAUSES, reason


class TestCameraOff:
    def test_the_first_camera_off_is_a_warning_not_a_termination(self, attempt):
        result = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)

        assert result['action'] == 'warned'
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.IN_PROGRESS

    def test_the_second_camera_off_ends_the_attempt(self, attempt):
        exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)
        result = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)

        assert result['action'] == 'terminated'
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == TerminationReason.CAMERA_OFF

    def test_the_warning_tells_them_to_turn_the_camera_back_on(self, attempt):
        detail = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)['detail']

        assert 'camera' in detail.lower()
        # The generic remedy would be actively unhelpful here.
        assert 'Stay in the assessment window' not in detail
        assert 'Turn your camera back on' in detail

    def test_it_is_recorded_as_a_violation_on_their_record(self, attempt):
        """Unlike system_issue: the candidate was told the camera must stay on, and the warning
        gave them a chance to put it right, so the second occurrence belongs on the record.
        """
        assert exam_session.is_violation_reason(TerminationReason.CAMERA_OFF) is True
        assert exam_session.is_violation_reason(TerminationReason.SYSTEM_ISSUE) is False

    def test_a_proctoring_event_is_logged_for_the_warning(self, attempt):
        exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)

        events = ProctoringEvent.objects.filter(attempt=attempt)
        assert events.count() == 1
        assert events.first().event_type == TerminationReason.CAMERA_OFF

    def test_staff_see_a_readable_label_not_the_raw_code(self):
        label = exam_session.termination_label(TerminationReason.CAMERA_OFF)
        assert label == 'Camera switched off or blocked during the exam'
        assert 'camera_off' not in label


class TestTheWarningBudgetIsShared:
    def test_a_warning_spent_on_a_tab_switch_is_not_available_for_the_camera(self, attempt):
        """One warning per attempt, not one per cause - otherwise a candidate could switch tabs
        once, switch the camera off once, and never be terminated.
        """
        first = exam_session.record_violation(attempt, TerminationReason.TAB_SWITCH)
        second = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)

        assert first['action'] == 'warned'
        assert second['action'] == 'terminated'

    def test_the_count_is_read_from_the_database_not_the_browser(self, attempt):
        """So reloading the page, or clearing storage, cannot hand out a fresh warning."""
        exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)
        assert exam_session.warnings_used(attempt) == 1

        # A completely fresh object, as a reload would produce.
        reloaded = ExamAttempt.objects.get(pk=attempt.pk)
        assert exam_session.warnings_used(reloaded) == 1
        assert exam_session.record_violation(reloaded,
                                             TerminationReason.CAMERA_OFF)['action'] == 'terminated'

    def test_only_one_warning_is_allowed(self):
        assert exam_session.MAX_WARNINGS == 1


class TestFirstStrikeCausesStillTerminateImmediately:
    @pytest.mark.parametrize('reason', [
        TerminationReason.DEVTOOLS_ATTEMPT,
        TerminationReason.SCREENSHOT_ATTEMPT,
        TerminationReason.VIEW_SOURCE_ATTEMPT,
    ])
    def test_no_warning_is_given(self, attempt, reason):
        result = exam_session.record_violation(attempt, reason)

        assert result['action'] == 'terminated'
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == reason
