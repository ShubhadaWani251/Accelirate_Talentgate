"""Azure Blob Storage for proctoring evidence: identity photos (block blobs), the continuous
session recording (an append blob, so ~10s MediaRecorder chunks can be uploaded as they're
produced instead of buffering the whole exam in browser memory), and - once
services.video_transcode has run - an MP4 copy of that same recording for a TA whose browser or
network won't play WebM comfortably (download_recording / upload_recording_mp4).

All uploads happen server-side - the candidate's browser never sees a storage key.

What gets STORED on ExamAttempt is the plain, unsigned blob URL: a pointer that carries no
credential. A short-lived read token is minted at read time by fresh_read_url() instead.

This replaced storing a URL with a 365-day SAS token baked into it, which had two distinct
problems. Every evidence row in the database was a long-lived bearer token - anyone who could
read the row, a log line, a support ticket or a screenshot had direct unauthenticated access to
a candidate's ID photo and full session recording, for a year. And because nothing ever
re-signed those URLs, rotating the storage account key would have instantly and permanently
broken every piece of historical evidence, with no repair path short of hand-rewriting rows.
Signing on read fixes both: the stored value survives key rotation, and a leaked URL expires
the same day.

fresh_read_url() re-signs whatever it is given, so rows written under the old scheme keep
working - their embedded token is discarded and replaced rather than trusted.

DEBUG-only local-disk fallback: with no AZURE_STORAGE_CONNECTION_STRING configured and
DEBUG=True, every function below writes under MEDIA_ROOT and returns a MEDIA_URL-based URL
instead of talking to Azure at all - lets the whole exam flow be exercised locally without real
cloud credentials. This path is never reachable with DEBUG=False (see settings.py).
"""

import logging
import os
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas,
)
from django.conf import settings

logger = logging.getLogger(__name__)

# How long a freshly-minted read URL stays valid. Short, because it no longer has to outlive
# anything - a URL is signed at the moment it is handed out, so a TA opening the evidence viewer
# a year from now gets a token minted then. Long enough to download a full session recording
# over a slow connection, short enough that a leaked URL stops working the same day.
_SAS_VALID_MINUTES = int(os.environ.get('EVIDENCE_URL_TTL_MINUTES', '120'))

_service_client = None


def _use_local_fallback():
    return settings.DEBUG and not settings.AZURE_STORAGE_CONNECTION_STRING


def _local_path(attempt_id, filename):
    directory = Path(settings.MEDIA_ROOT) / 'exam_evidence' / 'attempts' / str(attempt_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename


def _local_url(attempt_id, filename):
    return (
        f"{settings.LOCAL_MEDIA_BASE_URL.rstrip('/')}{settings.MEDIA_URL}"
        f"exam_evidence/attempts/{attempt_id}/{filename}"
    )


def _client():
    global _service_client
    if _service_client is None:
        _service_client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )
    return _service_client


def _container():
    container = _client().get_container_client(settings.AZURE_STORAGE_CONTAINER_EVIDENCE)
    if not container.exists():
        # Private by default (no `public_access=` passed) - every URL handed out embeds its own
        # SAS token instead of relying on the container being world-readable.
        container.create_container()
    return container


def fresh_read_url(stored_url, download_filename=None):
    """Mint a short-lived read URL for a stored evidence pointer. Returns None for no input.

    Call this at every point an evidence URL is handed to a browser or fetched server-side.
    Anything already on the URL's query string is discarded and replaced, so a row written under
    the old scheme (which baked a 365-day token into the stored value) is upgraded in passing
    rather than trusted.

    `download_filename`, when given, bakes a `Content-Disposition: attachment` response header
    override into the SAS token itself (Azure's `rscd` parameter) - the browser then downloads
    the file as an actual save-to-disk, with this name, instead of navigating to it. This is the
    ONLY way to make a download reliable here: the HTML `download` attribute on an <a> tag is
    silently ignored by every major browser for a cross-origin URL (which every blob URL is,
    from the frontend's own origin), so plain `<a href={blobUrl} download>` links did nothing
    visible - the browser just opened the resource instead of saving it. Leaving this None (the
    "view" case) omits the override, so the same blob opens inline instead of forcing a save
    dialog when the caller wants it displayed, not downloaded.

    Returns the input unchanged when there is nothing to sign - the local-disk fallback, or a
    URL that does not belong to the configured storage account. Signing failures degrade to
    returning the input rather than raising: an evidence link that does not work is a bad
    outcome, but a 500 on the candidate detail page - which shows much more than evidence - is
    a worse one, and the log records what happened.
    """
    if not stored_url:
        return None
    if _use_local_fallback() or not settings.AZURE_STORAGE_CONNECTION_STRING:
        # Same-origin in local dev (served off MEDIA_URL on this same host), so the plain
        # `download` attribute already works here - no header override needed.
        return stored_url

    try:
        parsed = urlparse(stored_url)
        # Path is /<container>/<blob name, which may itself contain slashes>.
        path = parsed.path.lstrip('/')
        container_name, _, blob_name = path.partition('/')
        if not container_name or not blob_name:
            return stored_url

        client = _client()
        # Only sign URLs that actually belong to this storage account. A stored value pointing
        # somewhere else (a stale local-media URL from development, say) must be passed through
        # untouched rather than have a token for the wrong account appended to it.
        if parsed.netloc.lower() != urlparse(client.url).netloc.lower():
            return stored_url

        sas_token = generate_blob_sas(
            account_name=client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(dt_timezone.utc) + timedelta(minutes=_SAS_VALID_MINUTES),
            content_disposition=(
                f'attachment; filename="{download_filename}"' if download_filename else None
            ),
        )
        # Rebuild from the parsed pieces so any pre-existing query string is dropped rather
        # than appended to, which would otherwise produce two sets of SAS parameters.
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path, '', sas_token, '',
        ))
    except Exception:
        logger.exception('Could not sign a read URL for stored evidence; returning it as stored')
        return stored_url


def _stored_url(blob_client):
    """The value persisted on ExamAttempt: the blob's address, with no credential attached."""
    return blob_client.url


def upload_photo(attempt_id, kind, data, content_type='image/jpeg'):
    """kind is 'id_photo' or 'face_photo'. Returns the unsigned URL to store on the attempt."""
    if _use_local_fallback():
        _local_path(attempt_id, f'{kind}.jpg').write_bytes(data)
        return _local_url(attempt_id, f'{kind}.jpg')

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/{kind}.jpg')
    blob_client.upload_blob(
        data, overwrite=True, content_settings=ContentSettings(content_type=content_type),
    )
    return _stored_url(blob_client)


def start_recording_blob(attempt_id):
    """Idempotent - if a recording already exists for this attempt (e.g. a resumed
    identity-capture retry), returns its URL rather than overwriting an in-progress recording.
    """
    if _use_local_fallback():
        path = _local_path(attempt_id, 'session_recording.webm')
        if not path.exists():
            path.touch()
        return _local_url(attempt_id, 'session_recording.webm')

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/session_recording.webm')
    try:
        blob_client.create_append_blob(
            content_settings=ContentSettings(content_type='video/webm'),
        )
    except ResourceExistsError:
        pass
    return _stored_url(blob_client)


def append_recording_chunk(attempt_id, chunk_bytes):
    """Azure append-blob limits (4 MiB/block, ~50,000 blocks) are nowhere near hit by a
    45-minute exam at ~10s chunks (~270 appends) - worth revisiting only if exam_duration_minutes
    is ever set drastically higher than the current defaults.
    """
    if _use_local_fallback():
        with open(_local_path(attempt_id, 'session_recording.webm'), 'ab') as f:
            f.write(chunk_bytes)
        return

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/session_recording.webm')
    blob_client.append_block(chunk_bytes)


def download_recording(attempt_id, dest_path):
    """Downloads the raw WebM recording to a local file path, for services.video_transcode -
    ffmpeg needs a real file (or stdin), not a Python bytes object, and downloading straight to
    disk rather than into memory first keeps a long recording from ever being fully buffered in
    the transcoding worker's RAM. Returns False (dest_path is left untouched) if there is no
    recording to download - an attempt that never got past identity capture, say.
    """
    if _use_local_fallback():
        source = _local_path(attempt_id, 'session_recording.webm')
        if not source.exists():
            return False
        dest_path.write_bytes(source.read_bytes())
        return True

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/session_recording.webm')
    if not blob_client.exists():
        return False
    with open(dest_path, 'wb') as f:
        blob_client.download_blob().readinto(f)
    return True


def upload_recording_mp4(attempt_id, local_path):
    """Uploads a transcoded MP4 file from local disk. Returns the unsigned URL to store on the
    attempt, same shape as every other upload_* function here.
    """
    if _use_local_fallback():
        _local_path(attempt_id, 'session_recording.mp4').write_bytes(local_path.read_bytes())
        return _local_url(attempt_id, 'session_recording.mp4')

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/session_recording.mp4')
    with open(local_path, 'rb') as f:
        blob_client.upload_blob(
            f, overwrite=True, content_settings=ContentSettings(content_type='video/mp4'),
        )
    return _stored_url(blob_client)


def delete_attempt_evidence(attempt_id):
    """Deletes every proctoring blob (both ID/face photos and the session recording) stored for
    one attempt. Used by the 30-day evidence retention sweep (services/evidence_retention.py) -
    called AFTER the caller has already decided the attempt is old enough, never a decision this
    function makes itself.

    Missing-file/missing-blob is not an error here: a photo that was never captured (an attempt
    abandoned before identity verification) has nothing to delete, and a second sweep run after a
    partial failure must not raise just because the first run already removed some of these.
    """
    filenames = (
        'id_photo.jpg', 'face_photo.jpg', 'session_recording.webm', 'session_recording.mp4',
    )
    if _use_local_fallback():
        for filename in filenames:
            path = _local_path(attempt_id, filename)
            path.unlink(missing_ok=True)
        return

    container = _container()
    for filename in filenames:
        blob_client = container.get_blob_client(f'attempts/{attempt_id}/{filename}')
        try:
            blob_client.delete_blob()
        except Exception:
            # Already gone, or never existed - either way there is nothing left to remove.
            pass
