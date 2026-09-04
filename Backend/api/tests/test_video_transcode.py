"""services/video_transcode.py - converting a candidate's WebM proctoring recording to MP4.

Runs the real, imageio_ffmpeg-bundled ffmpeg binary rather than mocking subprocess - this
module's entire job is invoking that binary correctly, so a test that never actually calls it
would not prove anything about the one thing that can genuinely go wrong (a wrong flag, a wrong
argument order). See test_transcode_recordings.py for the command's own query/locking/retry
logic, which mocks this module instead - those tests are about orchestration, not ffmpeg itself.
"""
import subprocess

import imageio_ffmpeg
import pytest

from api.services import blob_storage, video_transcode

pytestmark = pytest.mark.django_db


def _local_fallback(settings):
    settings.AZURE_STORAGE_CONNECTION_STRING = ''
    settings.DEBUG = True


@pytest.fixture
def real_webm_bytes(tmp_path):
    """A genuinely valid, tiny (well under a second) WebM file - vp8 video + opus audio, the
    same codecs a real candidate's MediaRecorder produces (see pickMimeType in
    useSessionRecorder.js) - generated with the same ffmpeg binary this module itself uses,
    so this fixture can never drift out of sync with what ffmpeg on this machine actually
    supports encoding.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    path = tmp_path / 'sample.webm'
    subprocess.run(
        [
            ffmpeg, '-y',
            '-f', 'lavfi', '-i', 'testsrc=duration=1:size=64x64:rate=5',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
            '-c:v', 'libvpx', '-c:a', 'libopus', str(path),
        ],
        capture_output=True, timeout=30, check=True,
    )
    return path.read_bytes()


class TestTranscodeToMp4Succeeds:
    def test_a_real_recording_converts_to_a_playable_mp4(
        self, settings, real_webm_bytes
    ):
        _local_fallback(settings)
        attempt_id = 90001
        blob_storage.start_recording_blob(attempt_id)
        blob_storage.append_recording_chunk(attempt_id, real_webm_bytes)

        mp4_url = video_transcode.transcode_to_mp4(attempt_id)

        assert mp4_url is not None
        assert mp4_url.endswith('session_recording.mp4')

    def test_the_uploaded_file_is_a_real_mp4_ffmpeg_can_read_back(
        self, settings, real_webm_bytes
    ):
        """Round-trips through ffprobe-equivalent behaviour (asking ffmpeg to read the file back
        and report its duration) rather than just checking the URL/extension - proves the bytes
        actually stored are a valid, decodable MP4, not just a renamed WebM (exactly the bug this
        feature exists to not repeat - see CandidateEvidenceZipView's old EVIDENCE_FILES entry).
        """
        _local_fallback(settings)
        attempt_id = 90002
        blob_storage.start_recording_blob(attempt_id)
        blob_storage.append_recording_chunk(attempt_id, real_webm_bytes)

        mp4_url = video_transcode.transcode_to_mp4(attempt_id)

        stored_path = blob_storage._local_path(attempt_id, 'session_recording.mp4')
        assert stored_path.exists()
        assert stored_path.stat().st_size > 0

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        # -f null discards decoded output - this only checks that ffmpeg can decode the file
        # start to finish without erroring, which a renamed-but-unconverted WebM would fail.
        result = subprocess.run(
            [ffmpeg, '-v', 'error', '-i', str(stored_path), '-f', 'null', '-'],
            capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
        assert mp4_url is not None


class TestTranscodeToMp4HandlesFailureGracefully:
    def test_no_recording_at_all_returns_none(self, settings):
        _local_fallback(settings)

        assert video_transcode.transcode_to_mp4(999999) is None

    def test_garbage_input_fails_cleanly_without_raising(self, settings):
        """An attempt whose recording is empty or corrupt (e.g. terminated before a single
        chunk landed) must not crash the whole scheduled run over one bad file - see
        transcode_recordings' own module docstring.
        """
        _local_fallback(settings)
        attempt_id = 90003
        blob_storage.start_recording_blob(attempt_id)
        blob_storage.append_recording_chunk(attempt_id, b'not a real webm file at all')

        result = video_transcode.transcode_to_mp4(attempt_id)

        assert result is None

    def test_an_empty_recording_fails_cleanly(self, settings):
        _local_fallback(settings)
        attempt_id = 90004
        blob_storage.start_recording_blob(attempt_id)

        result = video_transcode.transcode_to_mp4(attempt_id)

        assert result is None
