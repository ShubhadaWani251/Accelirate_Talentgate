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
  * The two-column band uses the fluid-hybrid pattern: inline-block divs that wrap naturally on
    a phone, with MSO conditional comments giving Outlook a real table to lay out instead. The
    parent sets font-size:0 to kill the whitespace gap between inline-block children.
"""

import html as html_lib

# Palette. Kept together so a change is one edit rather than a search through string literals.
NAVY = '#14213d'
INK = '#1c1e21'
MUTED = '#5f6b7a'
LINE = '#e3e6ea'
BLUE = '#0b5cab'
GREEN = '#1a7f37'
AMBER = '#9a6700'
RED = '#b3261e'

_STEP_TONES = {
    'blue': ('#eef4fc', BLUE),
    'green': ('#edf7f0', GREEN),
    'amber': ('#fdf6e6', AMBER),
    'red': ('#fdeeec', RED),
    'grey': ('#f5f6f8', NAVY),
}

FONT = 'Segoe UI,Helvetica,Arial,sans-serif'


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


def _two_columns(left, right):
    """Side by side on a desktop, stacked on a phone.

    inline-block wraps by itself when the screen is narrower than both columns, which needs no
    media query - Gmail strips those. Outlook ignores inline-block entirely, so the MSO comments
    hand it a real two-cell table instead.
    """
    return (
        '<div style="font-size:0;">'
        '<!--[if mso]><table role="presentation" width="640" cellpadding="0" cellspacing="0" '
        'border="0"><tr><td width="308" valign="top"><![endif]-->'
        '<div style="display:inline-block;width:100%;max-width:308px;vertical-align:top;">'
        f'{left}</div>'
        '<!--[if mso]></td><td width="24">&nbsp;</td><td width="308" valign="top"><![endif]-->'
        '<div style="display:inline-block;width:24px;">&nbsp;</div>'
        '<div style="display:inline-block;width:100%;max-width:308px;vertical-align:top;">'
        f'{right}</div>'
        '<!--[if mso]></td></tr></table><![endif]-->'
        '</div>'
    )


def _aadhaar_card_mock():
    """The front of an Aadhaar card, drawn in table cells.

    The same thing the instructions page draws in SVG - which no email client renders, hence
    this second construction. It marks the two fields verification reads and carries no real
    identity data: every value is a placeholder.
    """
    stripe = (
        f'<tr><td bgcolor="#ff9933" style="background:#ff9933;height:5px;line-height:5px;'
        f'font-size:0;">&nbsp;</td></tr>'
        f'<tr><td bgcolor="#138808" style="background:#138808;height:5px;line-height:5px;'
        f'font-size:0;">&nbsp;</td></tr>'
    )
    photo = (
        f'<td width="52" valign="top" style="width:52px;">'
        + _table(
            f'<tr><td height="62" bgcolor="#eef0f3" style="background:#eef0f3;height:62px;'
            f'border:1px solid {LINE};border-radius:4px;text-align:center;font-family:{FONT};'
            f'font-size:9px;color:{MUTED};">photo</td></tr>',
            width='52', style='width:52px;',
        )
        + '</td>'
    )
    fields = (
        f'<td valign="top" style="padding-left:10px;font-family:{FONT};font-size:11px;'
        f'color:{MUTED};line-height:1.6;">'
        f'Your Name<br>'
        f'<span style="color:{RED};font-weight:700;">DOB : DD/MM/YYYY</span><br>'
        f'Male / Female'
        f'</td>'
    )
    number = (
        f'<tr><td colspan="2" style="padding-top:8px;text-align:center;'
        f'font-family:Consolas,Menlo,monospace;font-size:15px;letter-spacing:2px;'
        f'font-weight:700;color:{RED};">XXXX XXXX 1234</td></tr>'
    )
    body = _table(
        f'<tr>{photo}{fields}</tr>{number}',
        width='100%', style='width:100%;',
    )
    return _table(
        stripe
        + f'<tr><td style="padding:10px 12px 12px;font-family:{FONT};font-size:10px;'
          f'color:{MUTED};text-align:center;">Government of India</td></tr>'
          f'<tr><td style="padding:0 12px 12px;">{body}</td></tr>',
        width='100%',
        style=f'width:100%;border:1px solid {LINE};border-radius:8px;background:#ffffff;',
    )


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
        + _lines([
            'Download and install it from ' + _link('https://safeexambrowser.org/download_en.html'),
            'Then open your configuration link:<br>' + _link(values['seb_config_link']),
        ], marker='&#8227;', colour=BLUE)
        + _note(
            'If that download is blocked by your browser or IT security software, use the ZIP '
            'version instead, extract it, and open the .seb file inside:<br>'
            + _link(values['seb_config_zip_link']),
            'amber',
        )
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

    step_rules = _card(
        _step_heading(5, 'During the Assessment', 'amber')
        + _lines([
            'Take the assessment alone and without assistance',
            'Do not share your assessment link with anyone',
            'Do not read questions aloud or talk - sustained talking is flagged',
            'Do not switch to other applications or leave the assessment',
            'Complete it in one uninterrupted session',
            'Submit before the window closes - it cannot be resumed afterwards',
        ], marker='&#8227;', colour=AMBER)
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

    content = (
        header + _spacer(18)
        + window_banner + _spacer(16)
        + _two_columns(step_prepare + _spacer(16) + step_aadhaar,
                       step_seb + _spacer(16) + step_camera)
        + _spacer(16)
        + step_rules + _spacer(16)
        + step_start + _spacer(16)
        + _two_columns(step_timing, step_help)
        + _spacer(20)
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
