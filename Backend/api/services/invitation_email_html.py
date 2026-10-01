"""The designed HTML alternative for the assessment invitation.

Every other email in this app has its HTML GENERATED from its plain text by
email_templates.text_body_to_html. The invitation does not: it is the one email whose job is to
walk a candidate through an eight-step setup - install a lockdown browser, photograph an ID,
check a camera - and a wall of paragraphs is the wrong shape for that. Numbered panels are.

That buys a real cost, stated plainly: the wording now exists twice, here and in
INVITATION_TEMPLATE's plain text, and the two can drift. test_invitation_html.py pins the facts
that must appear in both (the links, the window, the support address) so drift in anything
load-bearing fails the suite rather than reaching a candidate.

WHY IT IS BUILT THE WAY IT IS
-----------------------------
Email HTML is not web HTML. Outlook for Windows renders through Word, which has no flexbox, no
grid, no `white-space`, and drops `border-radius`. So:

  * Layout is nested <table role="presentation"> throughout. Tables are the only thing every
    client agrees on.
  * Every style is inline. <style> blocks are stripped by Gmail among others.
  * Colour is set with BOTH the bgcolor attribute and a CSS background, because Word honours the
    attribute and ignores some CSS shorthands.
  * Rounded corners degrade to square corners in Outlook. That is accepted, not worked around -
    the alternative is images, and see the next point.
  * NOTHING here is an image. Not the logo, not the icons, not the Aadhaar card - every one is
    drawn with table cells and text. Most clients block remote images by default, so an
    image-built version of this design arrives as a column of empty boxes for a large share of
    candidates. Drawn in HTML, it looks the same for everybody, needs no hosting, and cannot be
    broken by a blocked request.
  * Every panel is full width, one per step, stacked in step order. There is deliberately no
    multi-column band: a column here can only be a fixed pixel width (no media queries - Gmail
    strips them), which reads as a cramped ~300px of text on a phone, and it breaks the top-to-
    bottom reading order that numbered steps depend on.
"""

import html as html_lib

# Palette, taken from Frontend/src/styles/theme.css so this email and the screens a candidate
# lands on immediately afterwards are recognisably one product. The comment on each line names
# the variable it mirrors; these are literals because no email client resolves CSS variables.
# Values previously drifted a shade off the app's own on every one of these.
NAVY = '#0b1f4d'   # --brand-navy
INK = '#23272b'    # --text
MUTED = '#6b7280'  # --muted
LINE = '#d7dce2'   # --line-soft, deliberately not --line: these are panel edges, which in the
                   # app are the soft weight; --line (#9aa1a9) is for hard dividers and reads
                   # as a heavy box around every step here.
BLUE = '#0b63b8'   # --brand-blue-dark, deliberately not --brand-blue: this colours text and
                   # links on white, where the brighter #1289e8 is uncomfortably low-contrast.
GREEN = '#276b46'  # --green
AMBER = '#9a7b1f'  # --amber
RED = '#a80017'    # --red, which theme.css aliases to --brand-red-dark

# Tints are the app's own *-bg variables, so a red warning here is the red a candidate will see
# on the exam screens rather than a near-miss of it.
_STEP_TONES = {
    'blue': ('#e6f2fd', BLUE),    # --accent-soft
    'green': ('#e4f2e9', GREEN),  # --green-bg
    'amber': ('#fbf3dd', AMBER),  # --amber-bg
    'red': ('#fce9eb', RED),      # --red-bg
    'grey': ('#f5f6f8', NAVY),    # no theme equivalent - a neutral panel tint
}

FONT = 'Segoe UI,Helvetica,Arial,sans-serif'

# The filename of the setup guide attached to every invitation, named here rather than in
# services/invites.py (which does the attaching) so the copy below and the attachment itself
# cannot drift apart - an email naming a file that arrives under a different name is worse than
# one that names no file at all. invites.py imports this module already, so this direction of
# the dependency is the one that does not create a cycle.
SOP_ATTACHMENT_NAME = 'TalentGate-Assessment-Setup-SOP.pdf'


def _esc(value):
    return html_lib.escape(str(value or ''))


def _table(inner, **attrs):
    """A presentation table. role=presentation stops screen readers announcing layout as data."""
    extra = ''.join(f' {k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"{extra}>'
        f'{inner}</table>'
    )


def _card(inner, bg='#ffffff', border=LINE, pad=18):
    """One rounded panel. bgcolor as well as CSS - Word reads the attribute."""
    return _table(
        f'<tr><td bgcolor="{bg}" style="background:{bg};border:1px solid {border};'
        f'border-radius:10px;padding:{pad}px;">{inner}</td></tr>',
        width='100%', style='width:100%;',
    )


def _step_heading(number, title, tone='blue'):
    """A numbered badge beside a title. Two cells, not a floated circle - Word has no float."""
    bg, fg = _STEP_TONES[tone]
    badge = (
        f'<td width="26" bgcolor="{fg}" style="background:{fg};width:26px;height:26px;'
        f'border-radius:13px;text-align:center;vertical-align:middle;color:#ffffff;'
        f'font-family:{FONT};font-size:13px;font-weight:700;line-height:26px;">{number}</td>'
    )
    label = (
        f'<td style="padding-left:10px;font-family:{FONT};font-size:15px;font-weight:700;'
        f'color:{fg};">{_esc(title)}</td>'
    )
    return _table(f'<tr>{badge}{label}</tr>') + '<div style="height:10px;line-height:10px;">&nbsp;</div>'


def _lines(items, marker='✓', colour=GREEN):
    """A checklist. One row per item so a long line wraps under itself, not under the marker."""
    rows = ''.join(
        f'<tr>'
        f'<td width="16" valign="top" style="width:16px;font-family:{FONT};font-size:13px;'
        f'color:{colour};line-height:1.55;">{marker}</td>'
        f'<td style="padding:0 0 6px 6px;font-family:{FONT};font-size:13px;color:{INK};'
        f'line-height:1.55;">{item}</td>'
        f'</tr>'
        for item in items
    )
    return _table(rows, width='100%', style='width:100%;')


def _link(url, label=None):
    url = _esc(url)
    return (f'<a href="{url}" style="color:{BLUE};text-decoration:underline;'
            f'word-break:break-all;">{_esc(label) if label else url}</a>')


def _note(text, tone='red'):
    bg, fg = _STEP_TONES[tone]
    return _table(
        f'<tr><td bgcolor="{bg}" style="background:{bg};border-radius:8px;padding:10px 12px;'
        f'font-family:{FONT};font-size:12.5px;line-height:1.55;color:{fg};">{text}</td></tr>',
        width='100%', style='width:100%;margin-top:8px;',
    )


def _spacer(height=14):
    return f'<div style="height:{height}px;line-height:{height}px;font-size:0;">&nbsp;</div>'


def _aadhaar_card_mock():
    """The front of an Aadhaar card, drawn in table cells.

    The same thing the instructions page draws in SVG - which no email client renders, hence
    this second construction. It marks the two fields verification reads and carries no real
    identity data: every value is a placeholder.
    """
    # A saffron band with the wording in it, rather than a thin stripe above separate grey text.
    # The real card leads with that band, and it is most of what makes this readable as a card at
    # a glance instead of a shaded strip.
    header = (
        f'<tr><td bgcolor="#ff9933" style="background:#ff9933;padding:6px 12px;'
        f'font-family:{FONT};font-size:10.5px;font-weight:700;color:#ffffff;'
        f'letter-spacing:.3px;">Government of India</td></tr>'
    )
    photo = (
        f'<td width="58" valign="top" style="width:58px;">'
        + _table(
            # Portrait, near the 3:4 of the real photo box - a square read as an avatar.
            f'<tr><td height="72" bgcolor="#eef0f3" style="background:#eef0f3;height:72px;'
            f'border:1px solid {LINE};text-align:center;font-family:{FONT};'
            f'font-size:9px;color:{MUTED};">photo</td></tr>',
            width='58', style='width:58px;',
        )
        + '</td>'
    )
    fields = (
        f'<td valign="top" style="padding-left:10px;font-family:{FONT};font-size:11px;'
        f'color:{INK};line-height:1.7;">'
        f'Your Name<br>'
        f'<span style="color:{RED};font-weight:700;">DOB : DD/MM/YYYY</span><br>'
        f'<span style="color:{MUTED};">Male / Female</span>'
        f'</td>'
    )
    body = _table(f'<tr>{photo}{fields}</tr>', width='100%', style='width:100%;')
    # The number sits on its own band across the foot of the card, which is where the real one is
    # and what makes the layout recognisable rather than just a bordered box of text.
    number = (
        f'<tr><td bgcolor="#f7f8fa" style="background:#f7f8fa;border-top:1px solid {LINE};'
        f'padding:7px 12px;text-align:center;font-family:Consolas,Menlo,monospace;'
        f'font-size:15px;letter-spacing:2px;font-weight:700;color:{RED};">'
        f'XXXX XXXX 1234</td></tr>'
    )
    footer_stripe = (
        f'<tr><td bgcolor="#138808" style="background:#138808;height:5px;line-height:5px;'
        f'font-size:0;">&nbsp;</td></tr>'
    )
    # Fixed 320px and centred, NOT full width. A card that stretches to the panel is a strip, not
    # a card - the shape is most of the recognition, so it is pinned to roughly the real card's
    # 1.6:1 proportions and stays there however wide the panel gets.
    #
    # The width is given twice on purpose. The `width` ATTRIBUTE is what Outlook uses, since Word
    # ignores max-width; the CSS `width:100%;max-width:320px` is what every other client uses, and
    # is what keeps the card inside a 375px phone, where the panel's own padding leaves it well
    # under 320px to work with. align=center is the only centring Word honours.
    card = _table(
        header + f'<tr><td style="padding:12px;">{body}</td></tr>' + number + footer_stripe,
        width='320', align='center',
        # text-align:left stops the centring wrapper below from cascading into the card. Without
        # it the name, date of birth and gender centre themselves in their cell and float away
        # from the photo they belong beside - which is not how the document looks, and the whole
        # point of drawing it is that a candidate recognises their own card in it. The number
        # sets its own centring explicitly, so it is unaffected.
        style=f'width:100%;max-width:320px;border:1px solid {LINE};background:#ffffff;'
              f'text-align:left;',
    )
    # Wrapped because align="center" on the table is what Word honours, and this is what
    # everything else honours.
    return f'<div style="text-align:center;">{card}</div>'


def render_invitation_html(values):
    """The full invitation as designed HTML.

    `values` carries exactly what render_invitation_email already resolves: name, link,
    seb_config_link, seb_config_zip_link, start, end, support_email.
    """
    name = _esc(values['name'])
    link = values['link']
    start, end = _esc(values['start']), _esc(values['end'])
    support = _esc(values['support_email'])

    header = (
        f'<div style="font-family:{FONT};font-size:22px;font-weight:700;color:{NAVY};'
        f'line-height:1.3;">How to Start Your Assessment</div>'
        f'<div style="height:6px;line-height:6px;font-size:0;">&nbsp;</div>'
        f'<div style="font-family:{FONT};font-size:13.5px;color:{MUTED};line-height:1.6;">'
        f'Dear {name}, follow this guide to complete your Fresher Aptitude Assessment '
        f'smoothly and without any confusion.</div>'
    )

    window_banner = _card(
        f'<div style="font-family:{FONT};font-size:14px;font-weight:700;color:{NAVY};">'
        f'Your Assessment Details</div>'
        + _spacer(10)
        # Stacked rows, not two columns. A formatted window timestamp is ~24 characters
        # ("29-Sep-2026 07:08 PM IST"); side by side on a 375px phone the two ran together as
        # "07:08 PM IST29-Sep-2026". There is no media query to rescue it either - Gmail strips
        # them - so the layout has to be one that never needed rescuing.
        + _table(
            f'<tr><td style="font-family:{FONT};font-size:12.5px;color:{MUTED};'
            f'line-height:1.6;padding-bottom:8px;">Opens<br>'
            f'<span style="color:{INK};font-size:13.5px;font-weight:700;">{start}</span></td>'
            f'</tr>'
            f'<tr><td style="font-family:{FONT};font-size:12.5px;color:{MUTED};'
            f'line-height:1.6;">Closes<br>'
            f'<span style="color:{INK};font-size:13.5px;font-weight:700;">{end}</span></td>'
            f'</tr>',
            width='100%', style='width:100%;',
        )
        + _note('Your assessment link is active only during the window above.', 'red'),
        bg='#f3f7fd', border='#d6e4f7',
    )

    step_prepare = _card(
        _step_heading(1, 'Prepare Before You Start', 'blue')
        + _lines([
            'Laptop or desktop computer',
            'Stable internet connection',
            'Working camera and microphone',
            'Your Aadhaar Card (for identity verification)',
            'Safe Exam Browser (SEB) installed',
        ])
        # Named with its filename, and placed in step 1 rather than beside the SEB step: the
        # guide covers the whole journey, and an attachment nobody is told about is one nobody
        # opens. Blue, not red - it is help, not a rule.
        + _note(
            f'A step-by-step guide with screenshots is attached to this email as '
            f'<b>{_esc(SOP_ATTACHMENT_NAME)}</b>. It walks through everything below, including '
            f'installing Safe Exam Browser and preparing your Aadhaar. Open it first if you '
            f'would rather follow along with pictures.',
            'blue',
        )
    )

    step_seb = _card(
        _step_heading(2, 'Install & Open Safe Exam Browser', 'blue')
        # Red, not body text. This and the camera rule below are the two candidates most often
        # get wrong, and the plain-text half marks them **important** for the same reason - a
        # laid-out version that quietly demoted them to ordinary prose would be a regression
        # dressed as a redesign.
        + _note('<b>Required: this assessment must be taken inside Safe Exam Browser (SEB).</b> '
                'It is free, and it stops other applications and notifications reaching you '
                'during the exam.', 'red')
        + _spacer(10)
        # The two per-candidate configuration links that used to sit here are gone deliberately.
        # The assessment page offers both of them itself (ExamSebChoice.jsx renders the config
        # file and the zip fallback), so carrying them in the email duplicated the same URLs at
        # the point a candidate can least act on them - before SEB is even installed - and made
        # this the longest step in the message. They are still reachable, one step later, where
        # the candidate is already in front of the thing that uses them.
        + _lines([
            'Download and install it from ' + _link('https://safeexambrowser.org/download_en.html'),
            'Your configuration file is offered on the assessment page itself when you open '
            'your link in step 6 - there is nothing to download from this email.',
        ], marker='&#8227;', colour=BLUE)
    )

    step_aadhaar = _card(
        _step_heading(3, 'Keep Your Aadhaar Card Ready', 'green')
        + f'<div style="font-family:{FONT};font-size:13px;color:{INK};line-height:1.6;">'
          f'Identity verification runs before the assessment begins.</div>'
        + _spacer(10)
        + _aadhaar_card_mock()
        + _spacer(10)
        + _lines([
            'Use the <b>front</b> side of the card',
            'Your <b>date of birth</b> and the <b>Aadhaar number</b> must both be readable',
            'No glare, shadows or blur',
            'A masked card (XXXX XXXX 1234) is fine',
            'If it is not read correctly, you can retake the photo',
        ])
    )

    step_camera = _card(
        _step_heading(4, 'Camera & Microphone', 'green')
        + _note('<b>Your camera and microphone must remain enabled for the entire '
                'assessment.</b> Switching either off, or covering the camera, earns a warning '
                'from the same three-warning allowance as leaving the window.', 'red')
        + _spacer(10)
        + _lines([
            'Keep your face visible to the camera',
            'Check both are working before you begin',
        ])
    )

    # Two red notes bracket the bullets rather than joining them, because both carry a
    # consequence the bullets do not: what is being watched, and what happens when it sees
    # something. A candidate who learns either of these for the first time mid-exam has a
    # worse experience than one told here, and a termination nobody warned them about is the
    # complaint this panel exists to prevent.
    step_rules = _card(
        _step_heading(5, 'During the Assessment', 'amber')
        + _note(
            '<b>This assessment is AI-proctored.</b> Your camera and microphone are monitored '
            'for the whole assessment. Talking, looking away from the screen for a sustained '
            'period, another person appearing on camera, a phone or second screen in view, '
            'leaving the assessment window, and your face leaving the frame are all detected '
            'automatically.',
            'red',
        )
        + _spacer(10)
        + _lines([
            'Take the assessment alone and without assistance',
            'Do not share your assessment link with anyone',
            'Do not read questions aloud or talk - sustained talking is flagged',
            'Do not switch to other applications or leave the assessment',
            'Complete it in one uninterrupted session',
            'Submit before the window closes - it cannot be resumed afterwards',
        ], marker='&#8227;', colour=AMBER)
        # MAX_WARNINGS in services/exam_session.py. Stated as "the fourth ends it" rather than
        # "three strikes" because those are different rules and a candidate on their third
        # warning needs to know which one they are under. The keyboard shortcuts are called out
        # separately because they are NOT in WARNABLE_REASONS - they end an attempt outright,
        # and somebody who believed they had warnings in hand would be wrong about that.
        + _note(
            # "Your fourth violation", not "anything above": the bullets include things that are
            # not detectable events at all (sharing your link), so counting them would promise a
            # rule the server does not actually run. Violation is the system's own term for what
            # it records against an attempt.
            '<b>You are allowed three warnings.</b> Your fourth violation ends the assessment '
            'immediately and submits your answers as they are. Print Screen, F12 and Ctrl+U '
            'are never warned - they end it the first time.',
            'red',
        )
    )

    step_start = _card(
        _step_heading(6, 'Start Your Assessment', 'red')
        + f'<div style="font-family:{FONT};font-size:13px;color:{INK};line-height:1.6;">'
          f'Once you have read everything above, open your assessment link:</div>'
        + _spacer(12)
        + _table(
            f'<tr><td bgcolor="{BLUE}" style="background:{BLUE};border-radius:6px;'
            f'padding:12px 22px;text-align:center;">'
            f'<a href="{_esc(link)}" style="color:#ffffff;font-family:{FONT};font-size:14px;'
            f'font-weight:700;text-decoration:none;">Start Your Assessment &rarr;</a>'
            f'</td></tr>',
        )
        + _spacer(10)
        + f'<div style="font-family:{FONT};font-size:11.5px;color:{MUTED};line-height:1.55;'
          f'word-break:break-all;">Or paste this into SEB: {_link(link)}</div>'
        + _note(
            'Use your registered email address. This link is assigned to you alone and must '
            'not be shared.', 'red',
        )
    )

    step_timing = _card(
        _step_heading(7, 'Timing', 'grey')
        + _lines([
            f'Your window: <b>{start}</b> to <b>{end}</b>',
            'Start at least 30 minutes before it closes',
            'Once the window expires the link stops working',
        ], marker='&#8227;', colour=NAVY)
    )

    step_help = _card(
        _step_heading(8, 'Need Help?', 'grey')
        + _lines([
            'Take a screenshot of the error message',
            f'Email it with a short description to {_link("mailto:" + support, support)}',
        ], marker='&#8227;', colour=NAVY)
    )

    footer = (
        f'<div style="font-family:{FONT};font-size:12.5px;color:{MUTED};line-height:1.7;'
        f'text-align:center;">'
        f'We wish you all the very best, and thank you for your interest in building your '
        f'career with Accelirate.<br><br>'
        f'Kind regards,<br><b style="color:{INK};">Talent Acquisition Team</b><br>'
        f'Accelirate Softech Pvt. Ltd.</div>'
    )

    # One full-width panel per step, in step order, with an even gap between each.
    #
    # This replaced a two-column band for steps 1-4 and 7-8. Side by side, each panel was capped
    # at 308px, so text that reads as a short line on a desktop preview wrapped to five or six on
    # a phone, and the numbered steps no longer ran top to bottom - 1 and 3 were in the left
    # column while 2 and 4 sat to their right, which is the wrong reading order for something
    # whose whole structure is "do these in order". Full width also drops the fluid-hybrid
    # inline-block/MSO machinery the columns needed, so there is one layout to get right instead
    # of two that had to agree.
    content = (
        header + _spacer(18)
        + window_banner + _spacer(16)
        + step_prepare + _spacer(16)
        + step_seb + _spacer(16)
        + step_aadhaar + _spacer(16)
        + step_camera + _spacer(16)
        + step_rules + _spacer(16)
        + step_start + _spacer(16)
        + step_timing + _spacer(16)
        + step_help + _spacer(20)
        + footer
    )

    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head>'
        f'<body style="margin:0;padding:0;background:#ffffff;">'
        f'<div style="max-width:640px;margin:0 auto;padding:24px;background:#ffffff;">'
        f'{content}</div></body></html>'
    )
