"""Server-side validation for candidate-uploaded identity photos.

These arrive on the exam portal's identity-capture endpoint, which is UNAUTHENTICATED by design
(a candidate hasn't started their exam yet, so there's no session to authenticate) and gated only
by a valid, unexpired invitation token. Any candidate - which is to say, anyone who has ever
received an invitation email - can hit it.

The upload's declared content type was previously trusted verbatim: it was read from the
multipart Content-Type header the CLIENT sends for that field, passed straight through to
blob_storage.upload_photo, and stored on the blob unchanged. That value is not the file's real
type - it's just a string the client asserts. The photos are later opened directly by staff (the
Candidate Details evidence panel links to the URL with target="_blank" and no `download`
attribute), so the browser renders the response using whatever Content-Type the blob was stored
with. An upload claiming to be image/svg+xml or text/html, containing script, would have executed
in the storage account's origin the moment a TA clicked "View Full Image" - stored content
injection served back to staff as trusted evidence.

The real frontend only ever sends image/jpeg (services/webcam/PhotoCapture.jsx uses
canvas.toBlob(..., 'image/jpeg')), so an allowlist costs the legitimate flow nothing.
"""

ALLOWED_IMAGE_CONTENT_TYPES = frozenset({'image/jpeg', 'image/png'})

# A single identity photo. Comfortably above a JPEG from any webcam at reasonable quality;
# far below what would let one candidate meaningfully strain evidence storage.
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024


class InvalidImageUpload(Exception):
    """Raised with a message safe to show the candidate directly."""


def validate_identity_photo(uploaded_file, field_label):
    """Raises InvalidImageUpload if this upload cannot be trusted as an identity photo.

    Checks the claimed content type against an allowlist and enforces a size cap. This is a
    declared-type check, not magic-byte sniffing - it stops a client from asserting an
    executable content type, which is the actual exploit path (the browser trusts whatever
    content type the blob is STORED with, not what the bytes look like). It does not guarantee
    the bytes are a genuine JPEG; that is a data-quality concern for the identity review the TA
    already performs manually, not a security boundary.
    """
    content_type = (uploaded_file.content_type or '').split(';')[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise InvalidImageUpload(
            f'{field_label} must be a JPEG or PNG image. Please retake the photo and try again.'
        )
    if uploaded_file.size > MAX_PHOTO_SIZE_BYTES:
        raise InvalidImageUpload(
            f'{field_label} is too large (max {MAX_PHOTO_SIZE_BYTES // (1024 * 1024)}MB). '
            f'Please retake the photo and try again.'
        )
