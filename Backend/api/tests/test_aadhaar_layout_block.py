"""The Aadhaar card drawing in the invitation email.

Candidates were photographing the back of the card, or cropping the number off, and only found
out when the capture came back unreadable. The invitation now shows the shape of the front and
marks the two fields verification actually reads.

The drawing's lines are padded to equal width, so it only works in a fixed-width font. The HTML
alternative therefore has to put it in a <pre> - and the plain-text alternative has to not show
the fence markers that tell the HTML builder which paragraph that is.
"""
import re

import pytest


def squashed(text):
    """Runs of spaces collapsed, so an assertion is about the CONTENT of the drawing rather
    than the padding that keeps its box square - the padding is allowed to change.
    """
    return re.sub(r' +', ' ', text)

from api.services.email_templates import (
    AADHAAR_LAYOUT_BLOCK, INVITATION_TEMPLATE, MONOSPACE_FENCE, strip_monospace_fences,
    text_body_to_html,
)


class TestTheDrawingItself:
    def test_it_carries_no_real_identity_data(self):
        """It is a layout, not a specimen. Every field is a placeholder - the moment a real
        name, number or date appears here it stops being a diagram and starts being somebody's
        identity document reproduced in an email.
        """
        assert 'XXXX XXXX 1234' in squashed(AADHAAR_LAYOUT_BLOCK)
        assert 'DD/MM/YYYY' in AADHAAR_LAYOUT_BLOCK
        assert 'Your Name' in AADHAAR_LAYOUT_BLOCK
        assert not re.search(r'\b\d{2}/\d{2}/(19|20)\d{2}\b', AADHAAR_LAYOUT_BLOCK)
        # No run of 12 digits, masked or otherwise, that could read as a real number.
        assert not re.search(r'\d{5,}', AADHAAR_LAYOUT_BLOCK)

    def test_it_marks_both_fields_verification_reads(self):
        assert AADHAAR_LAYOUT_BLOCK.count('<-- needed') == 2

    def test_every_drawn_line_is_the_same_width(self):
        """The box collapses into a zigzag if these drift - the whole reason it needs a
        fixed-width font and a <pre>.
        """
        drawn = [
            line for line in AADHAAR_LAYOUT_BLOCK.split('\n')
            if line.startswith(('+', '|'))
        ]
        assert len(drawn) > 5
        assert len({len(line) for line in drawn}) == 1


class TestItReachesTheInvitation:
    def test_the_invitation_includes_it(self):
        assert AADHAAR_LAYOUT_BLOCK in INVITATION_TEMPLATE['body']

    def test_the_plain_text_alternative_shows_no_fences(self):
        """A plain-text client would otherwise print ``` above and below the drawing."""
        plain = strip_monospace_fences(INVITATION_TEMPLATE['body'])

        assert MONOSPACE_FENCE not in plain
        # The drawing itself survives - it is already fixed-width in plain text.
        assert 'XXXX XXXX 1234' in squashed(plain)
        assert '+---' in plain

    def test_stripping_fences_leaves_the_rest_of_the_email_alone(self):
        body = INVITATION_TEMPLATE['body']
        plain = strip_monospace_fences(body)

        assert 'Dear {name}' in plain
        assert '{link}' in plain
        # Only the two fence lines go.
        assert len(body.split('\n')) - len(plain.split('\n')) == 2


class TestTheHtmlAlternative:
    @pytest.fixture
    def html(self):
        return text_body_to_html(INVITATION_TEMPLATE['body'])

    def test_the_drawing_goes_into_a_pre(self, html):
        """Not a <p>. Outlook renders through Word, which ignores `white-space: pre-wrap` - the
        same reason this builder already uses explicit <p>/<br> instead.
        """
        match = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.S)

        assert match is not None
        assert '+---' in match.group(1)
        assert 'XXXX XXXX 1234' in squashed(match.group(1))

    def test_that_pre_asks_for_a_monospace_font(self, html):
        opening = re.search(r'<pre[^>]*>', html).group(0)

        assert 'monospace' in opening

    def test_no_fence_marker_survives_into_the_html(self, html):
        assert MONOSPACE_FENCE not in html

    def test_ordinary_paragraphs_are_still_paragraphs(self, html):
        """The fence handling must not swallow the rest of the email."""
        assert html.count('<p style') > 10
        assert 'Greetings from Accelirate' in html

    def test_a_body_with_no_fence_is_unaffected(self):
        out = text_body_to_html('One paragraph.\n\nAnd another.')

        assert '<pre' not in out
        assert out.count('<p style') == 2
