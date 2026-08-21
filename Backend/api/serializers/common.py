def format_aadhaar_last4(value):
    """Display form for the stored Aadhaar suffix.

    Replaces the old mask_aadhaar(): masking became meaningless once only the last 4 digits are
    stored at all - there is nothing left to hide. Kept as a function rather than reading the
    field directly so the display form stays in one place if it ever gains a prefix again.
    """
    value = (value or '').strip()
    return value or None
