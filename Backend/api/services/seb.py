"""Safe Exam Browser (SEB) integration for the candidate exam portal.

SEB is required by the frontend (ExamSebChoice.jsx has no "continue without it" option), but
this backend itself never enforces that - nothing here ever rejects a request for lacking a SEB
header. The only thing this module does with that header is *credit* an attempt as SEB-verified
when one genuinely shows up, for a TA to see later (see
serializers.candidates.CandidateDetailSerializer.get_timeline). That split is deliberate: a
frontend gate is all client-side JavaScript, trivially bypassed by anyone motivated enough
(hitting the API directly, or an old cached build) - so it was never a real enforcement boundary
to begin with, and turning it into a hard backend 400 would only break the one thing this design
still gets right, which is that record_seb_usage can never itself become the reason a genuine
SEB session fails partway through. See the "Lockdown & Detection Brief" this was planned against
for why SEB matters at all: real OS-level lockdown (blocking other apps and notifications) is
something no browser tab can do on its own, and SEB is the only piece of this that gets past
that - but only for candidates who can actually install it, which is exactly why the frontend
gate is a real (if bypassable) product decision, not a hard security control.

Config generation and the Browser Exam Key are unrelated to whether verification later succeeds.
Every candidate who is offered SEB gets a real, working .seb file regardless of whether
SEB_BROWSER_EXAM_KEY_SECRET happens to be configured; that setting only controls whether a
*returning* request can be credited as verified.
"""

import hashlib
import hmac
import plistlib

from django.conf import settings
from django.utils import timezone


def _browser_exam_key(invitation):
    """The value embedded in this invitation's .seb config, and independently recomputed here
    at verification time - never stored, so there is no second copy of it to keep in sync.

    Scoped to invitation.unique_link_token (not one shared key for every candidate) because a
    shared key would be extractable from any one candidate's own .seb file - a plain XML plist,
    not encrypted - and then replayable to forge a verified-looking header for a DIFFERENT
    candidate's exam. unique_link_token is already this app's trust boundary for reaching a
    candidate's own exam at all, so keying off it adds no new exposure.

    Returns None when SEB_BROWSER_EXAM_KEY_SECRET is unset - see build_config/verify_seb_request
    for what that means in each case. An empty string would still make a technically-valid (if
    guessable) HMAC key, which is exactly the confusing half-working state this avoids by
    treating "unconfigured" as its own explicit branch rather than falling through to one.
    """
    if not settings.SEB_BROWSER_EXAM_KEY_SECRET:
        return None
    return hmac.new(
        settings.SEB_BROWSER_EXAM_KEY_SECRET.encode('utf-8'),
        invitation.unique_link_token.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def build_config(invitation):
    """The .seb file bytes for one candidate's invitation - an XML property list, SEB's native
    config format. Encryption is optional and skipped here; nothing in this file needs the
    tamper-protection it adds, and it can be layered on later without changing this shape.

    Deliberately minimal for now - only the settings this integration actually depends on:
    startURL (so opening the file drops the candidate straight into their own exam), and the
    capture-permission keys the existing webcam/mic proctoring pipeline needs to keep working
    unchanged inside SEB. A fuller lockdown profile (quit/reload/taskbar/URL-filter keys) is a
    deliberate follow-up, not guessed at here - see the "Lockdown & Detection Brief" plan notes.
    """
    config = {
        # The landing screen, not /exam directly - email verification, camera permission,
        # full-screen, instructions and identity capture all still have to happen first, now
        # inside SEB instead of a regular browser tab.
        'startURL': f"{settings.FRONTEND_ORIGIN}/t/{invitation.unique_link_token}/",
        'allowVideoCapture': True,
        'allowAudioCapture': True,
    }
    key = _browser_exam_key(invitation)
    if key is not None:
        config['browserExamKey'] = key
    return plistlib.dumps(config, fmt=plistlib.FMT_XML)


def verify_seb_request(request, invitation):
    """Whether this specific request genuinely came from a correctly-configured SEB session for
    this invitation. False for every reason - no key configured, no header sent, or a header
    that doesn't match - is treated identically by every caller: as "no signal", never as proof
    the candidate isn't using SEB. See record_seb_usage for why that distinction matters.

    SEB sends X-SafeExamBrowser-RequestHash as SHA256(absolute_request_url + browser_exam_key),
    hex-encoded - Django exposes it as HTTP_X_SAFEEXAMBROWSER_REQUESTHASH per its standard header
    name mangling. Compared with hmac.compare_digest (constant-time) rather than == - this is
    still a credential comparison even though nothing downstream treats a mismatch as hostile.
    """
    key = _browser_exam_key(invitation)
    if key is None:
        return False
    received = request.META.get('HTTP_X_SAFEEXAMBROWSER_REQUESTHASH')
    if not received:
        return False
    expected = hashlib.sha256(
        (request.build_absolute_uri() + key).encode('utf-8')
    ).hexdigest()
    try:
        return hmac.compare_digest(received, expected)
    except (TypeError, ValueError):
        # A malformed header (wrong type/length) must never turn into a 500 on a response the
        # candidate's exam is waiting on - it just means this one request isn't verified.
        return False


def record_seb_usage(attempt, request, invitation):
    """Credit an attempt as SEB-verified the first time a genuine SEB request is seen for it -
    and only the first time. Deliberately monotonic: once attempt.seb_verified_at is set,
    nothing here can ever clear it again, and an unverified request never counts as evidence
    that a previously-verified session ended (a missing header on any single request could be a
    transient proxy quirk, or simply a request that predates SEB involvement - never treated as
    "SEB stopped being used"). That is what makes it safe to call this from more than one place
    (see views.exam.ExamIdentityCaptureView and ExamBeginView) without the two ever disagreeing.
    """
    if attempt.seb_verified_at is not None:
        return
    if verify_seb_request(request, invitation):
        attempt.seb_verified_at = timezone.now()
        attempt.save(update_fields=['seb_verified_at'])
