"""Single source of truth for candidate-facing email copy.

Every template the TA can pick from "Send Notification Mail" lives here, keyed by the same
string the frontend sends, so approved wording is changed in exactly one place rather than
being retyped in the UI. `{name}` is the only placeholder - it's substituted per recipient.

NOTE: the copy below is working text, not the approved Talent Acquisition wording. The
approved templates live in the Global Talent Acquisition SharePoint ("Fresher Hiring / Email
formats") and must replace the `subject`/`body` values here verbatim once available. The keys,
the API contract, and the UI do not need to change when that happens.
"""

NOTIFICATION_TEMPLATES = {
    'hold': {
        'label': 'On Hold',
        'subject': 'Accelirate TalentGate - Your Application Status',
        'body': (
            'Hi {name},\n\n'
            'Thank you for completing the assessment. Your application is currently on hold '
            'pending further review - we will update you shortly.\n\n'
            'Regards,\nTalent Acquisition Team\nAccelirate'
        ),
    },
    'cutoff': {
        'label': 'Cutoff Changed',
        'subject': 'Accelirate TalentGate - Revised Qualifying Cutoff',
        'body': (
            'Hi {name},\n\n'
            'Please note the qualifying cutoff for your section has been revised. Your result '
            'is being re-evaluated against the updated cutoff.\n\n'
            'Regards,\nTalent Acquisition Team\nAccelirate'
        ),
    },
    'shortlisted': {
        'label': 'Shortlisted',
        'subject': 'Accelirate TalentGate - You Have Been Shortlisted',
        'body': (
            'Hi {name},\n\n'
            'Congratulations! You have been shortlisted for the next round. Further details '
            'will follow by email shortly.\n\n'
            'Regards,\nTalent Acquisition Team\nAccelirate'
        ),
    },
    'fail': {
        'label': 'Result - Not Selected',
        'subject': 'Accelirate TalentGate - Assessment Result',
        'body': (
            'Hi {name},\n\n'
            'Thank you for taking the time to complete our online assessment. After careful '
            'review, we are unable to take your application forward at this stage.\n\n'
            'We appreciate your interest in Accelirate and encourage you to apply again in '
            'the future.\n\n'
            'Regards,\nTalent Acquisition Team\nAccelirate'
        ),
    },
}


# Sent from Batch Details -> "Send Certification Link". Unlike the templates above this one
# takes two TA-supplied URLs as well as the recipient's name: the copy is fixed so the TA only
# ever pastes the links, never rewrites the wording.
CERTIFICATION_TEMPLATE = {
    'subject': 'Accelirate TalentGate - Your Certification Links',
    'body': (
        'Hi {name},\n\n'
        'Congratulations on completing your assessment. Please use the links below to '
        'complete your certification.\n\n'
        'Certification Link 1:\n{link_one}\n\n'
        'Certification Link 2:\n{link_two}\n\n'
        'Please complete both steps at the earliest. If either link does not open, reply to '
        'this email and we will resend it.\n\n'
        'Regards,\nTalent Acquisition Team\nAccelirate'
    ),
}


def render_certification_email(candidate, link_one, link_two):
    """Resolve the fixed certification copy for one candidate with the TA's two links."""
    return CERTIFICATION_TEMPLATE['subject'], CERTIFICATION_TEMPLATE['body'].format(
        name=candidate.full_name, link_one=link_one, link_two=link_two,
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
