"""Single source of truth for candidate-facing email copy.

Every template the TA can pick from "Send Notification Mail" lives here, keyed by the same
string the frontend sends, so approved wording is changed in exactly one place rather than
being retyped in the UI.

The copy below is the approved Talent Acquisition wording (Global Talent Acquisition
SharePoint, "Fresher Hiring / Email formats"), reproduced verbatim. The document's
`[Candidate Name]` / `{{...}}` markers have been converted to Python format placeholders;
nothing else was reworded. Placeholders are substituted per recipient by the render_* helpers
at the bottom of this file - a template must only reference placeholders its own render helper
supplies, or .format() will raise at send time.

The bodies below stay plain text and remain the authoritative wording. Mail is sent as
multipart: this text as-is, plus an HTML alternative GENERATED from it by text_body_to_html()
at send time. That direction matters - a hand-written second copy would drift from the approved
one, and the approved one is the thing that must not change. The HTML version exists only so
URLs arrive as real hyperlinks; candidates previously had to copy the assessment link out of
the message by hand, which Outlook does not reliably auto-link.

Avoid non-ASCII characters here (the Windows console this is often run from is cp1252 and will
crash on them).
"""

import html as html_lib
import re
import zoneinfo
from datetime import timezone as dt_timezone

from django.conf import settings

_SIGNATURE = (
    'Regards,\n'
    'Talent Acquisition Team\n'
    'Accelirate Softech Pvt. Ltd.'
)

NOTIFICATION_TEMPLATES = {
    'hold': {
        'label': 'Application On Hold',
        'subject': 'Update on Your Recruitment Process',
        'body': (
            'Dear {name},\n\n'
            'Thank you for completing the Aptitude Assessment for Accelirate Softech Pvt. Ltd.\n\n'
            'We would like to inform you that your application is currently on hold due to '
            'internal hiring requirements. This does not indicate a rejection of your '
            'application.\n\n'
            'We will review your profile again as hiring requirements progress and will notify '
            'you of any updates.\n\n'
            'Thank you for your patience and understanding.\n\n'
            + _SIGNATURE
        ),
    },
    'cutoff': {
        'label': 'Cutoff Score Updated',
        'subject': 'Update Regarding Your Aptitude Test Evaluation',
        'body': (
            'Dear {name},\n\n'
            'Thank you for participating in the Aptitude Assessment for the opportunity at '
            'Accelirate Softech Pvt. Ltd.\n\n'
            'We would like to inform you that the evaluation cutoff for this assessment has '
            'been revised. As a result, your test has been re-evaluated based on the updated '
            'criteria.\n\n'
            'If you have qualified, our recruitment team will contact you regarding the next '
            'stage of the hiring process.\n\n'
            'We appreciate your interest in Accelirate Softech Pvt. Ltd. and wish you all the '
            'best.\n\n'
            + _SIGNATURE
        ),
    },
    'shortlisted': {
        'label': 'Qualified for Next Round',
        'subject': "Congratulations! You've Qualified for the Next Round",
        'body': (
            'Dear {name},\n\n'
            'Congratulations!\n\n'
            'Based on your performance in the Aptitude Assessment, you have qualified for the '
            'next stage of our recruitment process.\n\n'
            'Our Talent Acquisition team will contact you shortly with interview details.\n\n'
            'We look forward to speaking with you.\n\n'
            + _SIGNATURE
        ),
    },
    'fail': {
        'label': 'Not Qualified',
        'subject': 'Update on Your Application',
        'body': (
            'Dear {name},\n\n'
            'Thank you for taking the time to participate in the Aptitude Assessment for '
            'Accelirate Softech Pvt. Ltd.\n\n'
            'After careful evaluation, we regret to inform you that you have not met the '
            'qualifying criteria for the next stage of the selection process.\n\n'
            'We sincerely appreciate your interest in our organization and encourage you to '
            'apply for future opportunities that match your skills and experience.\n\n'
            'We wish you success in your future endeavors.\n\n'
            + _SIGNATURE
        ),
    },
    'review': {
        'label': 'Review in Process',
        'subject': 'Your Assessment is Under Review',
        'body': (
            'Dear {name},\n\n'
            'Thank you for completing the Aptitude Assessment for Accelirate Softech Pvt. Ltd.\n\n'
            'Your assessment has been successfully submitted and is currently under review by '
            'our recruitment team.\n\n'
            'We are evaluating your performance and will share the outcome once the review '
            'process is complete.\n\n'
            'Thank you for your patience.\n\n'
            + _SIGNATURE
        ),
    },
    'technical_issue': {
        'label': 'Technical Issue Acknowledgement',
        'subject': 'Update Regarding Your Aptitude Assessment',
        'body': (
            'Dear {name},\n\n'
            'We have received your request regarding the technical issue encountered during '
            'the Aptitude Assessment.\n\n'
            'Our team is reviewing the issue. If required, a new assessment link or revised '
            'schedule will be shared with you.\n\n'
            'Thank you for your patience and understanding.\n\n'
            + _SIGNATURE
        ),
    },
}


# Sent from Batch Details -> "Send Certification Link". The two UiPath course URLs are part of
# the approved copy and are NOT TA-supplied - the only per-send value is the deadline, so a TA
# can never accidentally email the wrong course link.
CERTIFICATION_TEMPLATE = {
    # No subject line was given for this one in the source document - supplied here to match
    # the house style of the others. Change freely; nothing depends on the wording.
    'subject': 'Certification Course Completion - Action Required',
    'body': (
        'Dear {name},\n\n'
        'Congratulations for clearing HR screening round! As part of the next step in the '
        'hiring process, we request you to complete the following certification requirements '
        'and share the proof within the given deadline.\n\n'
        'Course Details (Mandatory):\n\n'
        '1. Introduction to Automation Course | UiPath Academy\n'
        '   https://academy.uipath.com/courses/introduction-to-automation\n'
        '   - Platform: UiPath Academy\n'
        '   - Please share the PDF certificate/diploma after completion.\n\n'
        '2. Automation Developer Associate Training\n'
        '   https://academy.uipath.com/learning-plans/automation-developer-associate-training\n'
        '   - Platform: UiPath Academy\n'
        '   - Learning Plan: Automation Developer Associate Training\n'
        '   - Complete the first 11 modules\n'
        '   - Please share screenshots of the completed modules as proof.\n\n'
        'Deadline: {deadline}\n\n'
        'Kindly ensure that all required documents/screenshots are shared before the deadline, '
        'as this is an important part of the evaluation process.\n\n'
        'If you have any questions or face any issues while accessing the courses, feel free '
        'to reach out.\n\n'
        + _SIGNATURE
    ),
}


# The assessment invitation. Lives here with the rest of the candidate-facing copy rather than
# inline in services/invites.py, so all approved wording is in one file.
INVITATION_TEMPLATE = {
    # No subject line was given for this one in the source document either - supplied here.
    'subject': 'Invitation to the Accelirate Fresher Aptitude Assessment',
    'body': (
        'Dear {name},\n\n'
        'Greetings from Accelirate!\n\n'
        'Thank you for your interest in joining Accelirate. We are pleased to invite you to '
        'participate in our Fresher Aptitude Assessment, which is the next step in our '
        'recruitment process.\n\n'
        'Please find your assessment details below:\n\n'
        'Assessment Link:\n'
        '{link}\n\n'
        'Assessment Window:\n'
        'Start: {start}\n'
        'End: {end}\n\n'
        'Please Note: The assessment link will be active only during the above-mentioned '
        'assessment window.\n\n'
        'Important Instructions\n\n'
        '- Before clicking the assessment link, please clear your browser cache to avoid any '
        'loading issues.\n\n'
        '- Recommended: use Safe Exam Browser (SEB) for this assessment - a free lockdown '
        'browser that keeps other applications and notifications from interrupting you. If '
        'you already have it installed, click the link below to download your configuration '
        'file; opening it launches Safe Exam Browser directly into your assessment:\n'
        '{seb_config_link}\n'
        'If you do not have Safe Exam Browser installed, or prefer not to use it, you may '
        'continue with your regular browser instead using the assessment link above.\n\n'
        '- Please make sure your camera and microphone are working properly before you begin '
        'the assessment.\n\n'
        '- Before starting the assessment, please close all other applications and turn off '
        'notifications (email, chat, calls, etc.) on your device - on Windows, turn on Focus '
        'Assist (search "Focus assist" in the Start menu, or Settings > System > Focus '
        'assist); on a Mac, turn on Do Not Disturb / Focus from Control Center. Any '
        'interruption from another application during the assessment may be treated as a '
        'violation and could result in your assessment being terminated.\n\n'
        '- Access the assessment only through the unique link provided above. This link is '
        'exclusively assigned to you and must not be shared with anyone.\n\n'
        '- Use your registered email address to access the assessment. Only the invited '
        'candidate will be permitted to start the test.\n\n'
        '- Complete the assessment within the specified assessment window. Once the window '
        'expires, the assessment link will no longer be accessible.\n\n'
        '- Ensure that your camera and microphone remain enabled throughout the assessment, '
        'as they may be used for proctoring purposes.\n\n'
        '- Use a laptop or desktop with a stable internet connection and complete the '
        'assessment in one uninterrupted session.\n\n'
        '- Do not switch browser tabs, minimize the browser window, or open other '
        'applications during the assessment. Such activities may be detected and recorded by '
        'the system and could impact your assessment.\n\n'
        '- Submit your assessment before the allotted time expires. Once submitted, the '
        'assessment cannot be resumed or modified.\n\n'
        'Need Assistance?\n'
        'If you experience any technical issues while accessing or completing the assessment, '
        'please take a screenshot of the error and contact our Talent Acquisition Team.\n'
        'Email: {support_email}\n\n'
        'We wish you all the very best for your assessment and appreciate your interest in '
        'building your career with Accelirate.\n\n'
        'Kind regards,\n'
        'Talent Acquisition Team\n'
        'Accelirate Softech Pvt. Ltd.\n'
        'Email: {support_email}'
    ),
}

# Format used wherever an assessment window is shown to a candidate.
DATETIME_FORMAT = '%d-%b-%Y %I:%M %p'


def support_email():
    """Address candidates are told to contact for help.

    Falls back to DEFAULT_FROM_EMAIL so the invitation never goes out with a blank contact
    address if SUPPORT_EMAIL hasn't been configured.
    """
    return getattr(settings, 'SUPPORT_EMAIL', '') or settings.DEFAULT_FROM_EMAIL


def format_datetime(value):
    """Render an assessment-window timestamp for a candidate, in the display timezone, named.

    Two bugs in one, previously: `.strftime()` was called straight on the stored value, which is
    UTC (settings.TIME_ZONE), and the result carried no timezone label. A candidate in IST was
    told the window opened at "12:03 PM" for a batch the TA had set to 17:33 - the same instant,
    5h30m apart, with nothing on the page to reveal that. The staff UI never showed the problem
    because the browser localizes it automatically; email has no browser to do that.

    The zone is always named in the output, so the reader can tell what they're looking at even
    if DISPLAY_TIME_ZONE is later changed or they are in a different region.
    """
    if value is None:
        return ''
    if value.tzinfo is None:
        # Shouldn't happen with USE_TZ=True, but assuming UTC beats silently shifting by the
        # server's local offset.
        value = value.replace(tzinfo=dt_timezone.utc)
    local = value.astimezone(zoneinfo.ZoneInfo(settings.DISPLAY_TIME_ZONE))
    label = local.strftime('%Z') or settings.DISPLAY_TIME_ZONE
    return f'{local.strftime(DATETIME_FORMAT)} {label}'


def render_invitation_email(candidate, batch, link, sender=None, seb_config_link=None):
    """Resolve the approved invitation copy into (subject, body) for one candidate.

    `sender` is the staff user actually sending this invite (Invitation.sent_by) - candidates
    contact THEM, not a shared inbox, since that's who actually knows this candidate's batch and
    can act on a problem. Falls back to the generic support_email() only when there's no sender
    to name (Invitation.sent_by is SET_NULL, so a deleted user account leaves this null).

    `seb_config_link` is a plain https:// URL (not the seb:// launch scheme) deliberately - an
    ordinary URL is what text_body_to_html's _linkify below already turns into a real clickable
    link with zero extra work, whereas a custom URL scheme is not reliably clickable across mail
    clients (Outlook's Safe Links rewriting in particular). That unreliability is exactly why the
    seb:// link only ever appears on the in-app choice screen (ExamSebChoice.jsx), never in an
    email - see api/services/seb.py.
    """
    return INVITATION_TEMPLATE['subject'], INVITATION_TEMPLATE['body'].format(
        name=candidate.full_name,
        link=link,
        seb_config_link=seb_config_link,
        start=format_datetime(batch.link_valid_from),
        end=format_datetime(batch.link_valid_until),
        support_email=(sender.email if sender else None) or support_email(),
    )


def render_certification_email(candidate, deadline):
    """Resolve the fixed certification copy for one candidate with the TA's deadline."""
    return CERTIFICATION_TEMPLATE['subject'], CERTIFICATION_TEMPLATE['body'].format(
        name=candidate.full_name, deadline=deadline,
    )


# A URL runs to the first whitespace or '<'. Trailing sentence punctuation is trimmed below so
# "see https://x/y." doesn't produce a link ending in a full stop.
_URL_RE = re.compile(r'https?://[^\s<]+')
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_TRAILING_PUNCTUATION = '.,;:!?)]}\''


def _linkify(escaped_text):
    """Wrap URLs and email addresses in anchors. Input must ALREADY be HTML-escaped.

    Operating on escaped text is what keeps this safe: a candidate name or a template edit
    containing markup can never reach the output as live HTML. The matched span is already
    escaped, so it is valid both as the anchor text and inside the href attribute (an '&' is
    '&amp;' in both places).
    """
    def url_repl(match):
        url = match.group(0)
        trailing = ''
        while url and url[-1] in _TRAILING_PUNCTUATION:
            trailing = url[-1] + trailing
            url = url[:-1]
        if not url:
            return match.group(0)
        return (f'<a href="{url}" style="color:#0b5cab;text-decoration:underline;'
                f'word-break:break-all;">{url}</a>{trailing}')

    def email_repl(match):
        address = match.group(0)
        return f'<a href="mailto:{address}" style="color:#0b5cab;">{address}</a>'

    return _EMAIL_RE.sub(email_repl, _URL_RE.sub(url_repl, escaped_text))


def _cta_button(url, label):
    """A tappable button for the one action the email is asking for.

    Built to survive the three renderers that matter, which disagree about almost everything:

    - Outlook on Windows renders with Word, which IGNORES `display:inline-block` on an anchor.
      A styled <a> therefore collapses to plain underlined text there - the exact failure this
      is meant to fix. So the padding lives on the <td>, and the <a> is only text.
    - Word also ignores border-radius, so the button is square in Outlook and rounded
      elsewhere. That is accepted rather than worked around with VML, which would double the
      markup for a cosmetic corner.
    - Gmail strips <style> blocks, so everything here is inline; and it requires the anchor to
      carry its own colour, since it recolours unstyled links itself.

    `target="_blank"` and `rel="noopener"` keep the assessment out of the mail client's own
    embedded viewer where possible - the exam needs a real browser for full-screen and camera.

    The raw URL is still printed underneath by the caller. That redundancy is deliberate:
    clients that block styling, and the plain-text part itself, both need the link readable.
    """
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:18px 0;border-collapse:separate;"><tr>'
        '<td align="center" bgcolor="#0b5cab" '
        'style="border-radius:6px;padding:14px 32px;mso-padding-alt:14px 32px;">'
        f'<a href="{url}" target="_blank" rel="noopener" '
        'style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;'
        'font-weight:700;color:#ffffff;text-decoration:none;line-height:1;'
        f'white-space:nowrap;">{label}</a>'
        '</td></tr></table>'
    )


def text_body_to_html(text, cta_url=None, cta_label='Start Your Assessment'):
    """Build the HTML alternative for a plain-text email body.

    Paragraphs (text separated by a blank line) become <p> tags, and a single line break within
    a paragraph becomes <br> - built explicitly rather than left to `white-space: pre-wrap`,
    which was the previous approach. Outlook renders HTML mail through Word's engine, and Word
    does not honour `white-space: pre-wrap` at all: every line break collapsed, so a five-
    paragraph email (greeting, body, signature) arrived as one unbroken run-on sentence. <p>/<br>
    are Word-safe because Word lays out actual block and line elements rather than interpreting
    a CSS whitespace rule.

    `cta_url`, when given and present in the text, gets a button rendered above the bare URL
    at that spot - so the candidate has something obvious to click, and still has the link
    itself if their client strips the styling. Callers that have no single primary action
    (notifications, certification) leave it None and get plain linkified text.

    Styles are inline because email clients strip <style> blocks.
    """
    body = _linkify(html_lib.escape(text))

    if cta_url:
        # Matched against the escaped-and-linkified form, since that is what `body` now holds.
        escaped_url = html_lib.escape(cta_url)
        anchor = (f'<a href="{escaped_url}" style="color:#0b5cab;text-decoration:underline;'
                  f'word-break:break-all;">{escaped_url}</a>')
        if anchor in body:
            body = body.replace(
                anchor,
                _cta_button(escaped_url, html_lib.escape(cta_label)) + anchor,
                1,
            )

    # Split on a blank line for paragraphs; a lone '\n' inside one (e.g. the three-line
    # signature) becomes <br> rather than starting a new <p>. Consecutive blank lines would
    # otherwise produce empty <p></p> spacers, so those are dropped.
    paragraphs = [p for p in body.split('\n\n') if p.strip('\n')]
    body_html = ''.join(
        f'<p style="margin:0 0 16px 0;">{p.replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )

    # Body and card share the same white background on purpose: a lighter shade behind a
    # narrower centered card (the previous #f6f7f9/#ffffff split) reads fine in a client that
    # actually confines it to the card's edges, but Gmail's web reading pane is wider than the
    # 640px card and renders that outer shade across the full pane - which looks like two grey
    # boxes flanking the text rather than a subtle frame. One background avoids the seam
    # regardless of how wide the client renders it.
    return (
        '<html><body style="margin:0;padding:0;background:#ffffff;">'
        '<div style="max-width:640px;margin:0 auto;padding:24px;'
        'font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.6;'
        'color:#1c1e21;background:#ffffff;">'
        f'{body_html}'
        '</div></body></html>'
    )


def render_template(template_key, candidate):
    """Resolve a template key into (subject, body) for one candidate.

    Returns None for an unknown key so the caller can reject the request rather than silently
    sending something the TA didn't choose.
    """
    template = NOTIFICATION_TEMPLATES.get(template_key)
    if not template:
        return None
    return template['subject'], template['body'].format(name=candidate.full_name)
