"""CandidateEvidenceZipView - bundling a candidate's proctoring evidence into one zip.

Written alongside fixing a real bug found while adding MP4 support: EVIDENCE_FILES used to fetch
session_recording_url (the WebM) but name it session_recording.mp4 in the zip - so the file this
zip claimed was an MP4 would not actually play as one. TestTheRecordingIsNamedByWhatItActuallyIs
is the regression test for that fix specifically.
"""
from unittest.mock import MagicMock, patch
import io
import zipfile

import pytest
from django.utils import timezone

from api.models import ExamAttempt

pytestmark = pytest.mark.django_db


def _candidate_with_attempt(
    ta_user, make_batch, make_candidate, make_invitation, **attempt_kwargs
):
    batch = make_batch(ta_user)
    candidate = make_candidate(batch, ta_user)
    invitation = make_invitation(candidate, ta_user)
    ExamAttempt.objects.create(
        candidate=candidate,
        invitation=invitation,
        status=ExamAttempt.Status.SUBMITTED,
        submitted_at=timezone.now(),
        **attempt_kwargs,
    )
    return candidate


def _mock_urlopen_returning(content_by_url_substring):
    """A fake urlopen: looks up which canned bytes to return by matching a substring in the
    requested URL, so the same mock serves every evidence file in one test without caring about
    fresh_read_url's exact signing/query-string details.
    """
    def _open(url, timeout=10):
        for substring, content in content_by_url_substring.items():
            if substring in url:
                response = MagicMock()
                response.read.return_value = content
                response.__enter__.return_value = response
                response.__exit__.return_value = False
                return response
        raise AssertionError(f'Unexpected URL fetched: {url}')
    return _open


class TestTheRecordingIsNamedByWhatItActuallyIs:
    def test_the_webm_is_named_webm_in_the_zip(
        self, client_for, ta_user, make_batch, make_candidate, make_invitation,
    ):
        candidate = _candidate_with_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            session_recording_url='https://example.test/attempts/1/session_recording.webm',
        )

        with patch(
            'urllib.request.urlopen',
            side_effect=_mock_urlopen_returning({'session_recording.webm': b'WEBM-BYTES'}),
        ):
            response = client_for(ta_user).get(f'/api/candidates/{candidate.candidate_id}/evidence.zip')

        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert 'session_recording.webm' in archive.namelist()
        assert archive.read('session_recording.webm') == b'WEBM-BYTES'
        assert 'session_recording.mp4' not in archive.namelist()

    def test_when_an_mp4_also_exists_both_files_are_included_separately(
        self, client_for, ta_user, make_batch, make_candidate, make_invitation,
    ):
        candidate = _candidate_with_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            session_recording_url='https://example.test/attempts/1/session_recording.webm',
            session_recording_mp4_url='https://example.test/attempts/1/session_recording.mp4',
        )

        with patch(
            'urllib.request.urlopen',
            side_effect=_mock_urlopen_returning({
                'session_recording.webm': b'WEBM-BYTES',
                'session_recording.mp4': b'MP4-BYTES',
            }),
        ):
            response = client_for(ta_user).get(f'/api/candidates/{candidate.candidate_id}/evidence.zip')

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert archive.read('session_recording.webm') == b'WEBM-BYTES'
        assert archive.read('session_recording.mp4') == b'MP4-BYTES'

    def test_no_mp4_yet_is_simply_omitted_not_an_error(
        self, client_for, ta_user, make_batch, make_candidate, make_invitation,
    ):
        """Not yet transcoded (see transcode_recordings) must not block the rest of the zip -
        the webm alone is still useful evidence, same as before MP4 support existed.
        """
        candidate = _candidate_with_attempt(
            ta_user, make_batch, make_candidate, make_invitation,
            session_recording_url='https://example.test/attempts/1/session_recording.webm',
        )

        with patch(
            'urllib.request.urlopen',
            side_effect=_mock_urlopen_returning({'session_recording.webm': b'WEBM-BYTES'}),
        ):
            response = client_for(ta_user).get(f'/api/candidates/{candidate.candidate_id}/evidence.zip')

        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert archive.namelist() == ['session_recording.webm']
