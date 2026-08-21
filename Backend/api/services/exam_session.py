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
    CAMERA_OFF = 'camera_off'
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
    TerminationReason.CAMERA_OFF:
        'Your assessment was ended because your camera was switched off or blocked. Continuous '
        'video is required for the whole assessment.',
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
    TerminationReason.CAMERA_OFF: 'Camera switched off or blocked during the exam',
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


# ---------------------------------------------------------------- warning tier
#
# Leaving the exam window gets ONE warning before the attempt is ended. Only this family of
# reasons is warnable, and deliberately so:
#
#   - They can genuinely happen by accident. A notification stealing focus, a stray Alt+Tab, a
#     misplaced Esc - none of those is proof of cheating, and termination is irreversible.
#   - fullscreen_exit has to be in here even though the request was specifically about tabs:
#     on Chrome/Windows, switching away from a full-screen tab ALSO drops full-screen, so the
#     two arrive together. If fullscreen_exit stayed zero-tolerance it would win the reason
#     ranking and terminate on the very first tab switch, and the warning would never be seen.
#
# Everything else stays first-strike. A devtools/view-source/Print-Screen keypress is a
# deliberate act nobody performs by accident, and system_issue means the camera/mic feed is
# gone - the exam cannot continue at all, so "warning, don't do it again" would be nonsense.
WARNABLE_REASONS = {
    TerminationReason.TAB_SWITCH,
    TerminationReason.WINDOW_BLUR,
    TerminationReason.FULLSCREEN_EXIT,
    # The camera going off is warnable for a different reason than the window ones: it is often
    # recoverable. A privacy shutter, the OS camera toggle, or another application grabbing the
    # device all look identical to deliberately covering the lens, and the honest response to an
    # ambiguous signal is to say so and give the candidate a chance to put it right - which
    # terminating cannot. The second occurrence ends the attempt, so this is not a free pass.
    #
    # Note this is still a VIOLATION (it is not in _NON_VIOLATION_REASONS): the candidate was
    # told the camera must stay on, so it belongs on their record either way. system_issue stays
    # separate and non-violation for the case where the whole feed dies, which is not
    # recoverable and not something a warning can help with.
    TerminationReason.CAMERA_OFF,
}

# One warning, then out. Counted server-side (see record_violation) rather than in the browser,
# so reloading the page - or clearing storage - cannot hand out a fresh warning.
MAX_WARNINGS = 1

_WARNING_CAUSES = {
    TerminationReason.TAB_SWITCH:
        'you switched to a different browser tab, or the exam tab was hidden or minimized',
    TerminationReason.WINDOW_BLUR:
        'the exam window lost focus - for example Alt+Tab, clicking another window or the '
        'taskbar, or opening another application',
    TerminationReason.FULLSCREEN_EXIT:
        'the assessment left full-screen mode',
    TerminationReason.CAMERA_OFF:
        'your camera stopped sending video - it may be switched off, covered, blocked by a '
        'privacy shutter, or in use by another application',
}


# What the candidate should actually DO about it, which is not the same for every cause. Telling
# someone whose camera was switched off to "stay in the assessment window" is useless advice at
# the one moment they are relying on it.
_WARNING_REMEDIES = {
    TerminationReason.CAMERA_OFF:
        'Turn your camera back on now and leave it on until you submit',
}
_DEFAULT_WARNING_REMEDY = 'Stay in the assessment window until you submit'


def warning_message(reason_code):
    """The candidate-facing warning text - names the specific cause, what to do, then the
    consequence.

    Same principle as TERMINATION_MESSAGES: never one generic "you did something wrong" for
    every cause. The consequence is stated in full because this is the only notice they get.
    """
    cause = _WARNING_CAUSES.get(reason_code, 'the assessment window was left')
    remedy = _WARNING_REMEDIES.get(reason_code, _DEFAULT_WARNING_REMEDY)
    return (
        f'Warning: {cause}. '
        f'This is your only warning. {remedy} - if this '
        f'happens again your assessment will be ended immediately, your answers will be '
        f'submitted as they are, and it cannot be resumed.'
    )


def warnings_used(attempt):
    """How many warnings this attempt has already been given.

    Read from the ProctoringEvent stream rather than a counter column: the events are already
    recorded for the TA's evidence view, so there is no second source of truth to keep in step,
    and no migration needed.
    """
    from api.models import ProctoringEvent
    return ProctoringEvent.objects.filter(
        attempt=attempt, severity=ProctoringEvent.Severity.WARNING, is_violation=True,
    ).count()


def record_violation(attempt, reason_code):
    """Decide what a proctoring violation does: warn once, or end the attempt.

    Returns {'action', 'detail', 'reason', 'warnings_used', 'warnings_allowed'} where action is
    'warned', 'terminated', or 'already_closed'.

    The whole decision runs under a row lock on the attempt so two violations arriving together
    can't both read "0 warnings used" and both let the candidate off. The browser collapses
    simultaneous triggers into one call already (see the frontend's settle window), but that is
    a convenience, not a guarantee - this is the check that actually holds.
    """
    from api.models import ProctoringEvent

    with transaction.atomic():
        locked = (ExamAttempt.objects
                  .select_for_update()
                  .select_related('invitation__batch', 'candidate')
                  .get(pk=attempt.pk))

        if locked.status != ExamAttempt.Status.IN_PROGRESS:
            # Already finalized - a late duplicate call. Report the termination message rather
            # than pretending this was a fresh warning.
            return {
                'action': 'already_closed',
                'reason': locked.termination_reason or reason_code,
                'detail': TERMINATION_MESSAGES.get(
                    locked.termination_reason or reason_code,
                    TERMINATION_MESSAGES[TerminationReason.TAB_SWITCH],
                ),
                'warnings_used': warnings_used(locked),
                'warnings_allowed': MAX_WARNINGS,
            }

        used = warnings_used(locked)
        if reason_code in WARNABLE_REASONS and used < MAX_WARNINGS:
            ProctoringEvent.objects.create(
                attempt=locked, event_type=reason_code,
                event_details={'outcome': 'warned', 'warning_number': used + 1},
                is_violation=True,
                severity=ProctoringEvent.Severity.WARNING,
            )
            return {
                'action': 'warned',
                'reason': reason_code,
                'detail': warning_message(reason_code),
                'warnings_used': used + 1,
                'warnings_allowed': MAX_WARNINGS,
            }

        ProctoringEvent.objects.create(
            attempt=locked, event_type=reason_code,
            event_details={'outcome': 'terminated', 'warnings_used': used},
            is_violation=is_violation_reason(reason_code),
            severity=ProctoringEvent.Severity.CRITICAL,
        )
        finalize_attempt(locked, outcome='terminated', reason=reason_code)
        return {
            'action': 'terminated',
            'reason': reason_code,
            'detail': TERMINATION_MESSAGES[reason_code],
            'warnings_used': used,
            'warnings_allowed': MAX_WARNINGS,
        }


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
        # The link is consumed at exactly this moment - the candidate is now in the exam
        # window and the clock has started. Doing it here rather than at identity capture
        # means an abandoned photo step doesn't burn the invitation. Guarded by the same
        # started_at check so a reload/resume doesn't rewrite it.
        invitation = attempt.invitation
        if not invitation.is_link_used:
            invitation.is_link_used = True
            invitation.save(update_fields=['is_link_used'])
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
    # is_link_used is NOT set here. Identity capture is not the point of no return - a
    # candidate whose browser dies while taking their ID photo must still be able to reopen
    # the link and resume. The link is spent when they actually enter the exam window; see
    # begin_exam, which is the one place that flips it.
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


def _load_answers(attempt):
    return list(
        attempt.examanswer_set.select_related('question', 'question__section')
        .order_by('answer_id')
    )


# Fields _grade_sections writes, for a targeted bulk_update on re-grade.
GRADED_FIELDS = (
    ['total_correct', 'overall_score']
    + [f'{key}_score' for key in SECTION_ORDER]
    + [f'{key}_cleared' for key in SECTION_ORDER]
)


def _grade_sections(attempt, answers, batch):
    """Recompute per-section scores/cleared and the overall totals from already-marked answers,
    against the batch's CURRENT cutoffs. Returns all_cleared.

    Split out of finalize_attempt so re-grading after a cutoff change (see regrade_batch) runs
    exactly the same arithmetic rather than a second, drifting copy of it.

    NOTE on units: `<section>_score` and `total_correct` are RAW COUNTS of correct answers, while
    `overall_score` is a PERCENTAGE. Mixing those two up is what previously made a 2-out-of-40
    result render as "5/40" in the UI.
    """
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

    attempt.total_correct = total_correct
    attempt.overall_score = (
        round(Decimal(total_correct) / Decimal(len(answers)) * 100, 2) if answers else Decimal('0.00')
    )
    return all_cleared


def _write_candidate_result(candidate, passed):
    """finalize_attempt and regrade_attempt are the only writers of Candidate.result."""
    candidate.result = Candidate.Result.PASS if passed else Candidate.Result.FAIL
    candidate.save(update_fields=['result', 'overall_score'])


def regrade_attempt(attempt, batch=None):
    """Re-evaluate an already-graded attempt against the batch's current cutoffs.

    Only SUBMITTED attempts are re-graded: a TERMINATED attempt fails on proctoring grounds, so
    lowering a cutoff must not resurrect it, and an IN_PROGRESS one has no scores yet.

    Deliberately does NOT re-mark ExamAnswer.is_correct - the answers and the answer key are not
    what changed. Only the pass/fail verdict derived from them is recomputed.

    Returns True if anything actually changed.
    """
    if attempt.status != ExamAttempt.Status.SUBMITTED:
        return False

    batch = batch or attempt.invitation.batch
    before = [getattr(attempt, f) for f in GRADED_FIELDS]
    all_cleared = _grade_sections(attempt, _load_answers(attempt), batch)
    changed = before != [getattr(attempt, f) for f in GRADED_FIELDS]

    candidate = attempt.candidate
    new_result = Candidate.Result.PASS if all_cleared else Candidate.Result.FAIL
    result_changed = candidate.result != new_result or candidate.overall_score != attempt.overall_score

    if changed:
        attempt.save(update_fields=GRADED_FIELDS)
    if result_changed:
        candidate.overall_score = attempt.overall_score
        _write_candidate_result(candidate, all_cleared)
    return changed or result_changed


def regrade_batch(batch):
    """Re-grade every submitted attempt in a batch - called when its cutoffs change, so the
    pass/fail shown on Batch Details and Candidate Details reflects the new cutoffs immediately
    instead of the values stored at submit time. Returns the number of attempts affected.
    """
    attempts = ExamAttempt.objects.select_related('candidate', 'invitation__batch').filter(
        invitation__batch=batch, status=ExamAttempt.Status.SUBMITTED,
    )
    return sum(1 for attempt in attempts if regrade_attempt(attempt, batch))


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

    answers = _load_answers(attempt)
    answered = [a for a in answers if a.selected_option]
    for answer in answered:
        answer.is_correct = (answer.selected_option == answer.question.correct_option)
    if answered:
        ExamAnswer.objects.bulk_update(answered, ['is_correct'])

    batch = attempt.invitation.batch
    all_cleared = _grade_sections(attempt, answers, batch)
    attempt.total_answered = len(answered)

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
    candidate.overall_score = attempt.overall_score
    _write_candidate_result(candidate, outcome == 'submitted' and all_cleared)

    return attempt
