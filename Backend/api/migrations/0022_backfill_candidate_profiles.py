from django.db import migrations

# Inlined rather than imported from api.services.candidate_validation/candidate_profile:
# migrations must not depend on application code that can change shape later and silently
# break this historical step. Mirrors identity_key()/link_profile()'s logic as of when this
# migration was written.

MIRRORED_FIELDS = (
    'first_name', 'last_name', 'email', 'phone', 'aadhaar_last4',
    'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
)


def _normalize_name(value):
    return ' '.join((value or '').split()).casefold()


def backfill_candidate_profiles(apps, schema_editor):
    """One CandidateProfile per (Aadhaar last 4 + name) found across every existing Candidate
    row, so pre-existing data gets the same "one real person, one entry" grouping that new
    uploads get going forward (see api/services/candidate_profile.py).

    Processed oldest-first: the last row applied to a given profile is therefore always the
    most recently created one, so the backfilled profile ends up showing that row's data -
    consistent with the "recent entry wins" rule the live code applies on every new upload/edit.
    Rows with no Aadhaar are left with profile=None, same as they'd get today - there's nothing
    to key a match on.
    """
    Candidate = apps.get_model('api', 'Candidate')
    CandidateProfile = apps.get_model('api', 'CandidateProfile')

    profile_id_by_key = {}
    candidates = (
        Candidate.objects
        .exclude(aadhaar_last4='')
        .order_by('created_at')
        .only('candidate_id', *MIRRORED_FIELDS)
    )
    for candidate in candidates.iterator():
        last4 = (candidate.aadhaar_last4 or '').strip()
        if not last4:
            continue
        name = _normalize_name(f'{candidate.first_name or ""} {candidate.last_name or ""}')
        key = f'{last4}:{name}'
        field_values = {field: getattr(candidate, field) for field in MIRRORED_FIELDS}

        profile_id = profile_id_by_key.get(key)
        if profile_id is None:
            profile = CandidateProfile.objects.create(identity_key=key, **field_values)
            profile_id_by_key[key] = profile.profile_id
        else:
            CandidateProfile.objects.filter(pk=profile_id).update(**field_values)

        candidate.profile_id = profile_id_by_key[key]
        candidate.save(update_fields=['profile'])


def noop_reverse(apps, schema_editor):
    """Deliberately not reversed: the backfilled CandidateProfile rows are harmless to leave in
    place, and there is nothing destructive here to undo. Rolling back migration
    0021_candidate_profile (which this depends on) drops the column/table outright anyway."""


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_candidate_profile'),
    ]

    operations = [
        migrations.RunPython(backfill_candidate_profiles, noop_reverse),
    ]
