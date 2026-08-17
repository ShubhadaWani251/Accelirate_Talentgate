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

Kept as plain text deliberately: send_mail is called with `message=`, not `html_message=`, so
these bodies are what the candidate actually sees. Avoid non-ASCII characters here (the
Windows console this is often run from is cp1252 and will crash on them).
"""

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


def render_invitation_email(candidate, batch, link):
    """Resolve the approved invitation copy into (subject, body) for one candidate."""
    return INVITATION_TEMPLATE['subject'], INVITATION_TEMPLATE['body'].format(
        name=candidate.full_name,
        link=link,
        start=batch.link_valid_from.strftime(DATETIME_FORMAT),
        end=batch.link_valid_until.strftime(DATETIME_FORMAT),
        support_email=support_email(),
    )


def render_certification_email(candidate, deadline):
    """Resolve the fixed certification copy for one candidate with the TA's deadline."""
    return CERTIFICATION_TEMPLATE['subject'], CERTIFICATION_TEMPLATE['body'].format(
        name=candidate.full_name, deadline=deadline,
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
