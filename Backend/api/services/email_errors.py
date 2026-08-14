"""One exception tuple for "the email did not go out", whichever backend is configured.

Send sites catch EMAIL_SEND_ERRORS rather than a backend-specific exception, so switching
EMAIL_BACKEND between Graph and SendGrid doesn't turn every `except` into dead code - which
would let real delivery failures escape as unhandled 500s instead of being recorded.
"""

from anymail.exceptions import AnymailError

from api.services.graph_email import GraphEmailError

EMAIL_SEND_ERRORS = (GraphEmailError, AnymailError, OSError)
