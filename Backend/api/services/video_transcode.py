"""Converts one attempt's WebM proctoring recording to MP4.

WebM is what every real candidate browser actually produces (see
features/exam/webcam/useSessionRecorder.js on the frontend - MediaRecorder only really supports
WebM muxing across Chrome/Edge/Firefox), and that is what stays canonical: this module never
touches session_recording_url or deletes the original. It only ever adds a second,
session_recording_mp4_url, for a TA whose browser/network/corporate policy doesn't handle WebM
comfortably - see the "Access to file has been blocked" report that prompted this.

Uses imageio_ffmpeg rather than a system ffmpeg install: it ships a real static ffmpeg binary
inside the pip package itself (platform-specific wheels - win/linux/mac all covered), so this
works identically whether the app is deployed via Backend/Dockerfile or, as the one real
deployment actually is, App Service's code-deploy path on a stock Python image with no apt-get
access at all (see README's Deployment section). No system-level dependency to install anywhere.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from api.services import blob_storage

logger = logging.getLogger(__name__)

# Bounds one conversion. A wedged or pathological ffmpeg run must not hang the transcoding
# worker forever - real conversions finish in a small fraction of this on ordinary hardware,
# since this is a codec swap (vp8/opus -> h264/aac), not a heavy multi-pass re-encode.
TRANSCODE_TIMEOUT_SECONDS = 1800


def transcode_to_mp4(attempt_id):
    """Downloads, converts, and uploads - returns the new MP4 blob's URL, or None if there was
    nothing to convert (no WebM recording exists for this attempt) or the conversion failed.

    Failure is logged, never raised: the caller (transcode_recordings) processes many attempts
    in one run, and one candidate's corrupt or unusual recording must not stop every other
    attempt's video from being converted.
    """
    with tempfile.TemporaryDirectory(prefix=f'talentgate-transcode-{attempt_id}-') as tmp:
        webm_path = Path(tmp) / 'source.webm'
        mp4_path = Path(tmp) / 'output.mp4'

        if not blob_storage.download_recording(attempt_id, webm_path):
            return None

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        try:
            result = subprocess.run(
                [
                    ffmpeg, '-y', '-i', str(webm_path),
                    '-c:v', 'libx264', '-c:a', 'aac',
                    # Moves the moov atom to the front of the file - without it, a browser <video>
                    # player has to download the WHOLE file before it can start playing, since the
                    # index normally lands at the end. Free correctness-wise (same encoded content,
                    # just reordered), and this file exists specifically to be watched in a browser.
                    '-movflags', '+faststart',
                    str(mp4_path),
                ],
                capture_output=True, timeout=TRANSCODE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error(
                'ffmpeg timed out converting attempt_id=%s to MP4 after %ss',
                attempt_id, TRANSCODE_TIMEOUT_SECONDS,
            )
            return None

        if result.returncode != 0 or not mp4_path.exists():
            logger.error(
                'ffmpeg failed converting attempt_id=%s to MP4 (exit %s): %s',
                attempt_id, result.returncode,
                result.stderr.decode('utf-8', errors='replace')[-2000:],
            )
            return None

        return blob_storage.upload_recording_mp4(attempt_id, mp4_path)
