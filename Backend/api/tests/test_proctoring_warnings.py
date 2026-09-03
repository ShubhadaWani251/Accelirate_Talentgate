"""The warn-then-terminate tier, and which causes belong to it.

The rule is up to three warnings for anything a candidate can plausibly recover from, and no
warning at all for a deliberate keypress. The warning count is shared across all causes and
counted server-side, so a reload cannot buy another one. A warning that is never acknowledged is
its own separate zero-tolerance path - see TestWarningNotAcknowledged - independent of how many
of the three warnings have been used.
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
        TerminationReason.WARNING_NOT_ACKNOWLEDGED,
    ])
    def test_deliberate_keypresses_and_dead_feeds_do_not(self, reason):
        """A devtools or Print Screen keypress is nobody's accident. system_issue means the feed
        is gone, and there is nothing a warning could ask the candidate to do about it.
        warning_not_acknowledged means the candidate was already given a warning and didn't
        respond to it in time - a second warning for ignoring the first would defeat the point.
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

    def test_three_camera_offs_all_warn_the_fourth_ends_the_attempt(self, attempt):
        for _ in range(exam_session.MAX_WARNINGS):
            result = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)
            assert result['action'] == 'warned'

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
        gave them a chance to put it right, so the terminating occurrence belongs on the record.
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
    def test_the_budget_is_shared_across_different_causes_not_reset_per_cause(self, attempt):
        """Three warnings total per attempt, not three per cause - otherwise a candidate could
        exhaust the budget on tab switches and still get a fresh set for the camera.
        """
        first = exam_session.record_violation(attempt, TerminationReason.TAB_SWITCH)
        second = exam_session.record_violation(attempt, TerminationReason.WINDOW_BLUR)
        third = exam_session.record_violation(attempt, TerminationReason.FULLSCREEN_EXIT)
        fourth = exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)

        assert [first['action'], second['action'], third['action']] == ['warned'] * 3
        assert fourth['action'] == 'terminated'

    def test_the_count_is_read_from_the_database_not_the_browser(self, attempt):
        """So reloading the page, or clearing storage, cannot hand out a fresh warning."""
        for _ in range(exam_session.MAX_WARNINGS):
            exam_session.record_violation(attempt, TerminationReason.CAMERA_OFF)
        assert exam_session.warnings_used(attempt) == exam_session.MAX_WARNINGS

        # A completely fresh object, as a reload would produce.
        reloaded = ExamAttempt.objects.get(pk=attempt.pk)
        assert exam_session.warnings_used(reloaded) == exam_session.MAX_WARNINGS
        assert exam_session.record_violation(reloaded,
                                             TerminationReason.CAMERA_OFF)['action'] == 'terminated'

    def test_three_warnings_are_allowed(self):
        assert exam_session.MAX_WARNINGS == 3


class TestWarningMessageCountsDownAccurately:
    """The candidate is only ever shown this text once per warning - it has to say the true
    remaining count, not a hardcoded "this is your only warning" left over from when there was
    only one.
    """

    def test_the_first_of_three_states_two_remaining(self):
        detail = exam_session.warning_message(TerminationReason.TAB_SWITCH, 1, 3)
        assert 'Warning 1 of 3' in detail
        assert '2 warnings left' in detail

    def test_the_second_of_three_states_one_remaining_singular(self):
        detail = exam_session.warning_message(TerminationReason.TAB_SWITCH, 2, 3)
        assert 'Warning 2 of 3' in detail
        assert '1 warning left' in detail
        assert '1 warnings' not in detail

    def test_the_final_warning_says_so_explicitly(self):
        detail = exam_session.warning_message(TerminationReason.TAB_SWITCH, 3, 3)
        assert 'Warning 3 of 3' in detail
        assert 'final warning' in detail
        assert 'warnings left' not in detail

    def test_every_warning_states_the_response_deadline(self):
        detail = exam_session.warning_message(TerminationReason.TAB_SWITCH, 1, 3)
        assert f'{exam_session.WARNING_RESPONSE_SECONDS} seconds' in detail


class TestWarningNotAcknowledged:
    """The candidate's browser reports this itself once its own 10-second countdown on the
    warning modal runs out - see ExamAttemptPage's warning-response effect. Independent of how
    many of the three real warnings are left: ignoring a warning ends the attempt immediately
    either way, since letting it slide would make the whole response deadline optional.
    """

    def test_it_ends_the_attempt_even_with_warnings_still_available(self, attempt):
        exam_session.record_violation(attempt, TerminationReason.TAB_SWITCH)  # 1 of 3 used

        result = exam_session.record_violation(attempt, TerminationReason.WARNING_NOT_ACKNOWLEDGED)

        assert result['action'] == 'terminated'
        attempt.refresh_from_db()
        assert attempt.status == ExamAttempt.Status.TERMINATED
        assert attempt.termination_reason == TerminationReason.WARNING_NOT_ACKNOWLEDGED

    def test_it_is_recorded_as_a_violation(self):
        assert exam_session.is_violation_reason(TerminationReason.WARNING_NOT_ACKNOWLEDGED) is True


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
