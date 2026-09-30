"""The invitation's designed HTML alternative.

This is the one email whose HTML is hand-built rather than generated from its plain text, because
it is an eight-step setup guide - a layout, not prose. The price is that the wording now exists
twice, and the two copies can drift.

These tests pin the half of that which actually matters. Wording may legitimately differ between
a laid-out version and a plain-text one; the FACTS may not. A link, a window or a support address
that appears in one and not the other, or differently in each, is a candidate being told two
things by the same message.

They also pin the email-client constraints the layout depends on, which are invisible until
someone opens it in Outlook: tables not flexbox, inline styles not a stylesheet, and no images.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Invitation
from api.services.email_templates import invitation_values, render_invitation_email
from api.services.invitation_email_html import render_invitation_html

pytestmark = pytest.mark.django_db

VALUES = {
    'name': 'Priya Sharma',
    'link': 'https://example.test/t/TOKEN123',
    'seb_config_link': 'https://example.test/api/exam/token/TOKEN123/seb-config/',
    'seb_config_zip_link': 'https://example.test/api/exam/token/TOKEN123/seb-config.zip/',
    'start': '29-Sep-2026 07:08 PM IST',
    'end': '29-Sep-2026 08:13 PM IST',
    'support_email': 'ta@accelirate.com',
}


@pytest.fixture
def html():
    return render_invitation_html(VALUES)


class TestEveryFactReachesTheCandidate:
    @pytest.mark.parametrize('key', ['name', 'link', 'start', 'end', 'support_email'])
    def test_the_value_appears(self, html, key):
        assert VALUES[key] in html

    def test_the_assessment_link_is_a_real_anchor(self, html):
        """A candidate opening this in SEB must be able to click, not copy out of prose."""
        assert f'href="{VALUES["link"]}"' in html

    def test_the_seb_configuration_links_are_deliberately_not_here(self, html):
        """They live on the assessment page instead - ExamSebChoice.jsx renders both.

        Pinned as an absence because the obvious "fix" on reading step 2 is to paste them back:
        it mentions a configuration file and then does not link it. The reasoning is that the
        email reaches a candidate before SEB is installed, which is the one moment those URLs
        are useless, and they were the bulk of the longest step in the message. Re-adding them
        here would put the same two URLs in two places and make this step long again.
        """
        assert VALUES['seb_config_link'] not in html
        assert VALUES['seb_config_zip_link'] not in html

    def test_the_candidate_is_still_told_where_the_configuration_file_is(self, html):
        """Removing the links must not leave "install SEB" with no next step."""
        assert 'configuration file is offered on the assessment page' in html

    def test_the_support_address_is_mailto(self, html):
        assert f'href="mailto:{VALUES["support_email"]}"' in html


class TestItAgreesWithThePlainTextHalf:
    """The two formats are written separately but must not state different facts."""

    @pytest.fixture
    def both(self, ta_user, make_batch, make_candidate):
        batch = make_batch(ta_user)
        candidate = make_candidate(batch, ta_user)
        invitation = Invitation.objects.create(
            candidate=candidate, batch=batch, unique_link_token='html-parity-token',
            link_expired_at=timezone.now() + timedelta(days=2), sent_by=ta_user,
        )
        link = 'https://example.test/t/html-parity-token'
        seb = 'https://example.test/api/exam/token/html-parity-token/seb-config/'
        seb_zip = 'https://example.test/api/exam/token/html-parity-token/seb-config.zip/'
        _subject, text = render_invitation_email(
            candidate, invitation, link, ta_user, seb, seb_zip)
        values = invitation_values(candidate, invitation, link, ta_user, seb, seb_zip)
        return text, render_invitation_html(values), values

    @pytest.mark.parametrize('key', ['link', 'start', 'end', 'support_email'])
    def test_the_same_value_is_in_both_halves(self, both, key):
        text, html, values = both

        assert values[key] in text
        assert values[key] in html

    def test_both_halves_come_from_one_resolution(self, both):
        """invitation_values is called once per send and fed to both. If that were resolved
        separately for each format, the window could differ between them - the same message
        telling a candidate two different closing times.
        """
        text, html, values = both

        assert values['end'] in text and values['end'] in html


class TestItSurvivesRealEmailClients:
    def test_layout_is_tables_not_flexbox_or_grid(self, html):
        """Outlook renders through Word, which supports neither."""
        assert '<table' in html
        assert 'display:flex' not in html
        assert 'display:grid' not in html

    def test_there_is_no_stylesheet(self, html):
        """Gmail strips <style> blocks; every rule has to be inline."""
        assert '<style' not in html
        assert 'style="' in html

    def test_nothing_depends_on_an_image(self, html):
        """Most clients block remote images by default. An image-built version of this design
        arrives as a column of empty boxes - so the logo, the icons and the Aadhaar card are all
        drawn with table cells and text instead.
        """
        assert '<img' not in html

    def test_no_panel_is_laid_out_in_columns(self, html):
        """Every step is full width, so nothing depends on a fixed pixel column.

        A column in email can only be a fixed width - Gmail strips media queries - which meant
        ~300px of text on a phone and a reading order that ran 1, 3, 2, 4 down the page. The
        inline-block/MSO machinery that made columns work at all went with them, so there is now
        one layout rather than two that had to agree.
        """
        assert 'display:inline-block' not in html
        assert 'max-width:308px' not in html

    def test_every_panel_is_full_width(self, html):
        assert 'width:100%' in html

    def test_colour_is_set_by_attribute_as_well_as_css(self, html):
        """Word honours bgcolor and ignores some CSS background shorthands."""
        assert 'bgcolor=' in html

    def test_it_is_a_complete_document(self, html):
        assert html.startswith('<!doctype html>')
        assert html.rstrip().endswith('</html>')


class TestTheAadhaarCardMock:
    def test_it_marks_both_fields_verification_reads(self, html):
        assert 'DOB : DD/MM/YYYY' in html
        assert 'XXXX XXXX 1234' in html

    def test_it_carries_no_real_identity_data(self, html):
        """A layout, not a specimen - the same rule the instructions page's SVG follows."""
        import re
        assert 'Your Name' in html
        assert not re.search(r'\b\d{2}/\d{2}/(19|20)\d{2}\b', html)


class TestEscaping:
    def test_a_name_with_markup_cannot_inject(self):
        html = render_invitation_html({**VALUES, 'name': '<script>alert(1)</script>'})

        assert '<script>' not in html
        assert '&lt;script&gt;' in html

    def test_an_ampersand_is_escaped_exactly_once(self, html):
        """Pre-escaping a title and then escaping it again produced a literal '&amp;amp;' on
        screen - caught in a browser, pinned here.
        """
        assert '&amp;amp;' not in html
        assert 'Install &amp; Open Safe Exam Browser' in html


class TestThePaletteMatchesTheApp:
    """The email's colours must be the app's colours, not a near-miss of them.

    This is asserted against Frontend/src/styles/theme.css directly, because nothing else can:
    no email client resolves CSS variables, so the values have to be duplicated as literals here,
    and duplicated constants drift silently. They already had - every one of navy, ink, muted,
    line, blue, green, amber and red sat a shade off the app's own, which is the kind of thing
    nobody sees in isolation and everybody feels when the email and the first screen are open
    side by side.
    """

    @staticmethod
    def _theme_variables():
        import re
        from pathlib import Path

        theme = (Path(__file__).resolve().parents[3]
                 / 'Frontend' / 'src' / 'styles' / 'theme.css')
        if not theme.is_file():
            pytest.skip('Frontend/src/styles/theme.css not present in this checkout')
        return dict(re.findall(r'(--[a-z-]+):\s*(#[0-9a-fA-F]{3,8})\s*;', theme.read_text()))

    @pytest.mark.parametrize('constant, variable', [
        ('NAVY', '--brand-navy'),
        ('INK', '--text'),
        ('MUTED', '--muted'),
        # --line-soft, not --line: panel edges are the soft weight in the app too.
        ('LINE', '--line-soft'),
        # --brand-blue-dark, not --brand-blue: this colours text on white.
        ('BLUE', '--brand-blue-dark'),
        ('GREEN', '--green'),
        ('AMBER', '--amber'),
        # theme.css aliases --red to --brand-red-dark, which a hex-only parse cannot follow.
        ('RED', '--brand-red-dark'),
    ])
    def test_the_constant_matches_its_theme_variable(self, constant, variable):
        from api.services import invitation_email_html

        theme = self._theme_variables()
        assert variable in theme, f'{variable} is gone from theme.css'

        assert getattr(invitation_email_html, constant).lower() == theme[variable].lower()

    @pytest.mark.parametrize('tone, variable', [
        ('blue', '--accent-soft'),
        ('green', '--green-bg'),
        ('amber', '--amber-bg'),
        ('red', '--red-bg'),
    ])
    def test_the_note_tints_match_too(self, tone, variable):
        """A red warning here should be the red the exam screens use, not a similar one."""
        from api.services.invitation_email_html import _STEP_TONES

        theme = self._theme_variables()

        assert _STEP_TONES[tone][0].lower() == theme[variable].lower()
