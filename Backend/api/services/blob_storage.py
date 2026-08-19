"""Azure Blob Storage for proctoring evidence: identity photos (block blobs) and the
continuous session recording (an append blob, so ~10s MediaRecorder chunks can be uploaded
as they're produced instead of buffering the whole exam in browser memory).

All uploads happen server-side - the candidate's browser never sees a storage key. URLs handed
back to the frontend/stored on ExamAttempt carry a long-lived read SAS token, so
views.candidates.CandidateEvidenceZipView's existing `urllib.request.urlopen(url)` keeps working
completely unmodified.

DEBUG-only local-disk fallback: with no AZURE_STORAGE_CONNECTION_STRING configured and DEBUG=True,
every function below writes under MEDIA_ROOT and returns a MEDIA_URL-based URL instead of talking
to Azure at all - lets the whole exam flow be exercised locally without real cloud credentials.
This path is never reachable with DEBUG=False (see settings.py).
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas,
)
from django.conf import settings

# How long a stored evidence URL keeps working once issued. Generous rather than tight - a TA
# reviewing evidence weeks after a batch closes shouldn't hit an expired link, and re-signing
# retroactively isn't built (nothing currently re-writes these URLs after they're first set).
_SAS_VALID_DAYS = 365

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


def _blob_url_with_sas(blob_client):
    sas_token = generate_blob_sas(
        account_name=blob_client.account_name,
        container_name=blob_client.container_name,
        blob_name=blob_client.blob_name,
        account_key=_client().credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(dt_timezone.utc) + timedelta(days=_SAS_VALID_DAYS),
    )
    return f"{blob_client.url}?{sas_token}"


def upload_photo(attempt_id, kind, data, content_type='image/jpeg'):
    """kind is 'id_photo' or 'face_photo'. Returns a SAS-secured URL (or a local dev URL)."""
    if _use_local_fallback():
        _local_path(attempt_id, f'{kind}.jpg').write_bytes(data)
        return _local_url(attempt_id, f'{kind}.jpg')

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/{kind}.jpg')
    blob_client.upload_blob(
        data, overwrite=True, content_settings=ContentSettings(content_type=content_type),
    )
    return _blob_url_with_sas(blob_client)


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
    return _blob_url_with_sas(blob_client)


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


def recording_url(attempt_id):
    if _use_local_fallback():
        return _local_url(attempt_id, 'session_recording.webm')

    blob_client = _container().get_blob_client(f'attempts/{attempt_id}/session_recording.webm')
    return _blob_url_with_sas(blob_client)
