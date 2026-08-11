def mask_aadhaar(value):
    if not value or len(value) < 4:
        return None
    return f'XXXX-XXXX-{value[-4:]}'
