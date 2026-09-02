"""Resolves and maintains the one CandidateProfile row per real person (by Aadhaar last 4 +
date of birth), so the same person's Candidate rows across different batches aggregate onto one
entry for the All Candidates page instead of fragmenting into one row per batch appearance.
"""

from api.models import CandidateProfile
from api.services.candidate_validation import candidate_identity_key

# Same set as EDITABLE_FIELDS in candidate_validation.py (views/batches.py's Upload Review
# edit form) - the person-level fields a profile mirrors from whichever Candidate row supplied
# them most recently.
PROFILE_MIRRORED_FIELDS = (
    'first_name', 'last_name', 'email', 'phone', 'aadhaar_last4', 'date_of_birth',
    'college_name', 'degree', 'stream', 'percentage', 'passing_out_year', 'location',
)


def _profile_key(candidate):
    last4, dob_iso = candidate_identity_key(candidate)
    return f'{last4}:{dob_iso}'


def link_profile(candidate):
    """Resolve (or create) the CandidateProfile matching `candidate`'s identity, overwrite its
    mirrored fields with `candidate`'s own - the most recently uploaded/edited row always wins -
    and point `candidate.profile` at it.

    No-op (returns None) when the candidate has no Aadhaar or DOB to key on: there's nothing to
    match against, the same early-out services/duplicate_check.run_duplicate_check applies.
    """
    if not candidate.aadhaar_last4 or not candidate.date_of_birth:
        return None

    key = _profile_key(candidate)
    profile, _created = CandidateProfile.objects.get_or_create(
        identity_key=key,
        defaults={field: getattr(candidate, field) for field in PROFILE_MIRRORED_FIELDS},
    )
    for field in PROFILE_MIRRORED_FIELDS:
        setattr(profile, field, getattr(candidate, field))
    profile.save()

    if candidate.profile_id != profile.profile_id:
        candidate.profile = profile
        candidate.save(update_fields=['profile'])
    return profile
