from django.db import migrations

# Inlined rather than imported from api.services.candidate_profile/candidate_validation:
# migrations must not depend on application code that can change shape later and silently break
# this historical step. Mirrors _profile_key()/link_profile() as of when this was written.

PROFILE_MIRRORED_FIELDS = (
    'first_name', 'last_name', 'email', 'phone', 'aadhaar_last4', 'date_of_birth',
    'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
)


def _identity_key(candidate):
    last4 = (candidate.aadhaar_last4 or '').strip()
    dob = candidate.date_of_birth
    return f'{last4}:{dob.isoformat() if dob else ""}'


def relink_stale_profiles(apps, schema_editor):
    """Re-point every Candidate whose profile no longer matches its own Aadhaar + date of birth.

    Editing a candidate from Candidate Details used to change that pair without re-running
    link_profile, so the row kept pointing at the profile for the identity it USED to have. All
    Candidates collapses to one row per profile, so the same real person appeared two or three
    times over, each under a different stale profile - which is exactly the bug reported against
    the live data, where three rows sharing Aadhaar 2737 and DOB 2003-08-26 sat under profiles
    keyed 2334:2006-09-29, 2737:1992-09-05 and 2737:2003-08-26.

    The serializer now re-links on every edit, so this cannot recur; this repairs the rows that
    were already mis-linked before that fix landed.

    Oldest-first, so the most recently created row is the last to write its mirrored fields onto
    a shared profile - the same "most recent entry wins" rule link_profile applies live.

    Profiles left with no members are NOT deleted. Nothing reads a profile except through a
    Candidate, so an orphan is inert, and deleting rows during a repair risks removing one that
    another candidate outside this pass legitimately still keys to.
    """
    Candidate = apps.get_model('api', 'Candidate')
    CandidateProfile = apps.get_model('api', 'CandidateProfile')

    profiles_by_key = {p.identity_key: p for p in CandidateProfile.objects.all()}

    for candidate in (
        Candidate.objects.select_related('profile').order_by('created_at').iterator()
    ):
        # Same early-out as link_profile: nothing to key on, so nothing to match against.
        if not (candidate.aadhaar_last4 or '').strip() or not candidate.date_of_birth:
            continue

        key = _identity_key(candidate)
        if candidate.profile_id is not None and candidate.profile.identity_key == key:
            continue  # already correct

        profile = profiles_by_key.get(key)
        if profile is None:
            profile = CandidateProfile.objects.create(
                identity_key=key,
                **{field: getattr(candidate, field) for field in PROFILE_MIRRORED_FIELDS},
            )
            profiles_by_key[key] = profile
        else:
            for field in PROFILE_MIRRORED_FIELDS:
                setattr(profile, field, getattr(candidate, field))
            profile.save()

        candidate.profile = profile
        candidate.save(update_fields=['profile'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0033_candidate_result_decided_at_and_more'),
    ]

    operations = [
        # Irreversible in the only sense that matters: reversing would have to restore links
        # that were wrong, and the correct link is always recomputable from the row itself.
        migrations.RunPython(relink_stale_profiles, migrations.RunPython.noop),
    ]
