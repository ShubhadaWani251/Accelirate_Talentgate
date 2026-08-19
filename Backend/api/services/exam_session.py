"""Start/resume, timer authority, autosave, and scoring for one candidate's exam attempt.

Working on plain values/model instances rather than requests, same as
services/candidate_validation.py - lets the auth layer, the session-state view, and the
management-command safety net all share exactly one finalize path (see finalize_attempt).
"""

from decimal import Decimal
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from api.models import Candidate, ExamAnswer, ExamAttempt, Invitation
from api.services.question_selection import (
    SECTION_LABELS, SECTION_ORDER, select_questions_for_attempt,
)


class TerminationReason:
    """Every way an attempt can be ended early, one per distinct candidate-facing message -
    a single generic "you did something wrong" message was explicitly rejected in favor of
    telling the candidate exactly what triggered it.
    """
    TAB_SWITCH = 'tab_switch'
    WINDOW_BLUR = 'window_blur'
    FULLSCREEN_EXIT = 'fullscreen_exit'
    DEVTOOLS_ATTEMPT = 'devtools_attempt'
    VIEW_SOURCE_ATTEMPT = 'view_source_attempt'
    SCREENSHOT_ATTEMPT = 'screenshot_attempt'
    SYSTEM_ISSUE = 'system_issue'


TERMINATION_MESSAGES = {
    TerminationReason.TAB_SWITCH:
        'Your assessment was ended because you switched to a different browser tab, or the exam '
        'tab was hidden or minimized.',
    TerminationReason.WINDOW_BLUR:
        'Your assessment was ended because the exam window lost focus - for example by pressing '
        'Alt+Tab, clicking another window or the taskbar, or opening another application.',
    TerminationReason.FULLSCREEN_EXIT:
        'Your assessment was ended because you exited full-screen mode.',
    TerminationReason.DEVTOOLS_ATTEMPT:
        'Your assessment was ended because you attempted to open developer tools.',
    TerminationReason.VIEW_SOURCE_ATTEMPT:
        'Your assessment was ended because you attempted to view the page source.',
    TerminationReason.SCREENSHOT_ATTEMPT:
        'Your assessment was ended because a screenshot attempt (Print Screen) was detected.',
    TerminationReason.SYSTEM_ISSUE:
        'Your assessment was ended because of a technical issue - camera/microphone access was lost.',
}

# Short staff-facing labels for the same codes, used wherever a TA/Admin reads a candidate's
# history. The candidate-facing sentences above are too long for a table cell, but the raw code
# ('window_blur') is not something a TA should ever be shown either.
TERMINATION_LABELS = {
    TerminationReason.TAB_SWITCH: 'Switched tab / tab hidden',
    TerminationReason.WINDOW_BLUR: 'Left the exam window (Alt+Tab or another app)',
    TerminationReason.FULLSCREEN_EXIT: 'Exited full-screen',
    TerminationReason.DEVTOOLS_ATTEMPT: 'Tried to open developer tools',
    TerminationReason.VIEW_SOURCE_ATTEMPT: 'Tried to view page source',
    TerminationReason.SCREENSHOT_ATTEMPT: 'Screenshot attempt (Print Screen)',
    TerminationReason.SYSTEM_ISSUE: 'Technical issue - camera/microphone lost',
}


def termination_label(reason_code):
    """Human-readable label for a stored termination_reason.

    Falls back to the raw value so a reason stored before this map existed (or by a future code
    path that forgets to register one) still shows *something* rather than blanking the cell.
    """
    if not reason_code:
        return 'No reason recorded'
    return TERMINATION_LABELS.get(reason_code, reason_code)


# Reasons not attributable to anything the candidate chose to do - the attempt still ends (an
# exam can't safely continue once the camera/mic feed is gone), but it shouldn't be flagged as a
# proctoring violation on their record the way a deliberate tab-switch or devtools attempt is.
_NON_VIOLATION_REASONS = {TerminationReason.SYSTEM_ISSUE}


def is_violation_reason(reason_code):
    return reason_code not in _NON_VIOLATION_REASONS


def remaining_seconds(attempt):
    """Server-authoritative countdown - the only clock that matters. A tampered client-side
    timer can't extend an attempt past this, since every write endpoint checks it via
    CandidateAttemptAuthentication before doing anything else.

    `started_at` is null until the candidate actually opens the exam window (see begin_exam), so
    before that the full duration is still ahead. Returning the full duration rather than 0 here
    matters: 0 would make the client render an already-expired countdown on the identity screen.
    """
    duration_minutes = attempt.invitation.batch.exam_duration_minutes
    if not attempt.started_at:
        return duration_minutes * 60
    deadline = attempt.started_at + timedelta(minutes=duration_minutes)
    return max(0, int((deadline - timezone.now()).total_seconds()))


def is_expired(attempt):
    """An attempt that hasn't begun can never be expired - its clock hasn't started."""
    return attempt.started_at is not None and remaining_seconds(attempt) <= 0


def begin_exam(attempt):
    """Start the clock. Called once, when the candidate actually reaches the exam window - NOT at
    identity capture, so time spent capturing photos or reading instructions is never charged
    against the exam duration.

    Idempotent: a reload/resume re-hits this and keeps the original started_at rather than
    granting a fresh full duration (which would otherwise be a trivial way to get unlimited time).
    """
    if attempt.started_at is None:
        attempt.started_at = timezone.now()
        attempt.save(update_fields=['started_at'])
    return attempt


def _assign_questions(attempt, batch):
    questions_by_section = select_questions_for_attempt(batch)
    answers = [
        ExamAnswer(attempt=attempt, question=question)
        for section_key in SECTION_ORDER
        for question in questions_by_section[section_key]
    ]
    ExamAnswer.objects.bulk_create(answers)


@transaction.atomic
def start_or_resume_attempt(invitation_id, ip_address, user_agent):
    """Creates the ExamAttempt (+ its randomized question set) on first call, or returns the
    existing one on a retried/duplicate identity-capture submit.

    Locks the Invitation row (not the not-yet-existing ExamAttempt row) so two concurrent
    identity-capture requests for the same invitation can't both pass the "does an attempt
    already exist" check and each create a full question set - the second request blocks on
    this lock until the first commits, then sees the attempt the first one created.

    Returns (attempt, created).
    """
    invitation = (
        Invitation.objects.select_for_update()
        .select_related('batch', 'candidate')
        .get(pk=invitation_id)
    )
    try:
        return ExamAttempt.objects.select_related('invitation', 'invitation__batch').get(
            invitation=invitation
        ), False
    except ExamAttempt.DoesNotExist:
        pass

    attempt = ExamAttempt.objects.create(
        candidate=invitation.candidate,
        invitation=invitation,
        # started_at stays null here on purpose - the clock starts only when the candidate opens
        # the exam window (begin_exam), so identity capture and reading the instructions don't
        # eat into their exam time.
        status=ExamAttempt.Status.IN_PROGRESS,
        ip_address=ip_address,
        user_agent=(user_agent or '')[:255],
    )
    _assign_questions(attempt, invitation.batch)
    invitation.is_link_used = True
    invitation.save(update_fields=['is_link_used'])
    return attempt, True


def save_answer(attempt, question_id, selected_option, time_spent_seconds=None):
    """Idempotent UPDATE, never an insert - the question must already be one of this attempt's
    assigned ExamAnswer rows (created at start time). Raises ExamAnswer.DoesNotExist if not,
    which the view translates to a 404.
    """
    answer = attempt.examanswer_set.get(question_id=question_id)
    answer.selected_option = selected_option or None
    answer.answered_at = timezone.now() if selected_option else None
    if time_spent_seconds is not None:
        answer.time_spent_seconds = time_spent_seconds
    answer.save(update_fields=['selected_option', 'answered_at', 'time_spent_seconds'])
    return answer


def build_session_state(attempt):
    """Render payload for GET /api/exam/session/ - never includes correct_option."""
    answers = list(
        attempt.examanswer_set.select_related('question', 'question__section')
        .order_by('answer_id')
    )
    sections = {key: {'key': key, 'label': SECTION_LABELS[key], 'questions': []} for key in SECTION_ORDER}
    for answer in answers:
        question = answer.question
        sections[question.section.section_key]['questions'].append({
            'question_id': question.question_id,
            'question_text': question.question_text,
            'option_a': question.option_a,
            'option_b': question.option_b,
            'option_c': question.option_c,
            'option_d': question.option_d,
            'selected_option': answer.selected_option,
        })
    return {
        'remaining_seconds': remaining_seconds(attempt),
        'sections': [sections[key] for key in SECTION_ORDER if sections[key]['questions']],
    }


def finalize_attempt(attempt, outcome, reason=None):
    """Score the attempt and close it out. Idempotent - a no-op if it isn't IN_PROGRESS
    anymore, which is what lets auto-finalize-on-expired-auth, an explicit submit, and the
    tab-switch terminate endpoint all call this without racing each other.

    `outcome` is 'submitted' (manual submit AND time-expiry - a candidate who ran out of time
    did nothing wrong, so it's scored like a normal submission) or 'terminated' (the tab-switch/
    window-blur proctoring violation).
    """
    if attempt.status != ExamAttempt.Status.IN_PROGRESS:
        return attempt

    answers = list(
        attempt.examanswer_set.select_related('question', 'question__section')
        .order_by('answer_id')
    )
    answered = [a for a in answers if a.selected_option]
    for answer in answered:
        answer.is_correct = (answer.selected_option == answer.question.correct_option)
    if answered:
        ExamAnswer.objects.bulk_update(answered, ['is_correct'])

    batch = attempt.invitation.batch
    total_correct = 0
    all_cleared = True
    for section_key in SECTION_ORDER:
        section_answers = [a for a in answers if a.question.section.section_key == section_key]
        total = len(section_answers)
        correct = sum(1 for a in section_answers if a.is_correct)
        total_correct += correct

        if total == 0:
            cleared = None
        else:
            cutoff = getattr(batch, f'{section_key}_cutoff')
            cleared = (Decimal(correct) / Decimal(total) * 100) >= cutoff
            if not cleared:
                all_cleared = False

        setattr(attempt, f'{section_key}_score', correct)
        setattr(attempt, f'{section_key}_cleared', cleared)

    attempt.total_answered = len(answered)
    attempt.total_correct = total_correct
    attempt.overall_score = (
        round(Decimal(total_correct) / Decimal(len(answers)) * 100, 2) if answers else Decimal('0.00')
    )

    now = timezone.now()
    if outcome == 'submitted':
        attempt.status = ExamAttempt.Status.SUBMITTED
        attempt.submitted_at = now
    else:
        attempt.status = ExamAttempt.Status.TERMINATED
        attempt.terminated_at = now
        attempt.termination_reason = reason
    attempt.save()

    # First writer of these two fields anywhere in the codebase - Candidate.result has never
    # been set before this (services/invites.py only ever moves candidate.status). A terminated
    # attempt fails outright, matching the wireframe's zero-tolerance framing.
    candidate = attempt.candidate
    candidate.result = (
        Candidate.Result.PASS if (outcome == 'submitted' and all_cleared) else Candidate.Result.FAIL
    )
    candidate.overall_score = attempt.overall_score
    candidate.save(update_fields=['result', 'overall_score'])

    return attempt
