"""The org-wide exam configuration every NEW batch is created from.

Stored as Setting rows rather than a model, because there is exactly one of it. The per-section
half is keyed BY SECTION KEY ('exam_config.section.data_interp.questions') rather than by a
column name, so a section added from Question Bank Management gets a default the moment it
exists - which is what lets a new section reach a new batch without a code change.

Changing a default never reaches a batch candidates have been told about: each one snapshots its
sections into BatchSection rows at creation (see views/batches.py), exactly as it used to
snapshot the columns.

DRAFT batches are the exception - they follow the defaults, because nothing has been sent for one
yet. See resync_draft_batches below.
"""
from django.db import transaction

from api.models import QuestionBankSection, Setting

SETTING_GROUP = 'exam_config'

# Settings that are not per-section. name -> parser for the stored string value.
GENERAL_KEYS = {
    'exam_duration_minutes': int,
}

GENERAL_FALLBACKS = {
    'exam_duration_minutes': 45,
}

# What a section gets when nobody has configured one for it yet - a section added ten minutes
# ago has no saved default, and a new batch still has to be creatable.
FALLBACK_SECTION_QUESTIONS = 10
FALLBACK_SECTION_CUTOFF = 70.0
# A newly added section is INCLUDED by default. The alternative - added but silently left out of
# every batch - makes "I added a section and nothing happened" the first experience of the
# feature, and unticking it here is one click.
FALLBACK_SECTION_INCLUDED = True


def _setting_key(name):
    return f'{SETTING_GROUP}.{name}'


def _section_setting_key(section_key, field):
    return _setting_key(f'section.{section_key}.{field}')


def get_batch_defaults():
    """{exam_duration_minutes, sections: [{section_key, section_name, question_count, cutoff,
    included}]}.

    EVERY active section is returned, included or not - Configure Default Batch renders one
    tickbox per section and needs the unticked ones to show at all. Callers that want only the
    sections a new batch should actually get use included_sections() below.

    A retired section (is_active=False) is left out entirely: it must not turn up on a new batch,
    while the batches that already used it keep their own rows untouched.
    """
    rows = {
        row.setting_key: row.setting_value
        for row in Setting.objects.filter(setting_group=SETTING_GROUP)
    }

    result = {}
    for name, caster in GENERAL_KEYS.items():
        raw = rows.get(_setting_key(name))
        result[name] = caster(raw) if raw is not None else GENERAL_FALLBACKS[name]

    sections = []
    for section in QuestionBankSection.objects.filter(is_active=True):
        raw_count = rows.get(_section_setting_key(section.section_key, 'questions'))
        raw_cutoff = rows.get(_section_setting_key(section.section_key, 'cutoff'))
        raw_included = rows.get(_section_setting_key(section.section_key, 'included'))
        sections.append({
            'section_id': section.section_id,
            'section_key': section.section_key,
            'section_name': section.section_name,
            'question_count': int(raw_count) if raw_count is not None
            else FALLBACK_SECTION_QUESTIONS,
            'cutoff': float(raw_cutoff) if raw_cutoff is not None else FALLBACK_SECTION_CUTOFF,
            'included': (raw_included == 'True') if raw_included is not None
            else FALLBACK_SECTION_INCLUDED,
        })
    result['sections'] = sections
    return result


def included_sections(defaults=None):
    """Just the sections a new batch should be created with."""
    return [s for s in (defaults or get_batch_defaults())['sections'] if s['included']]


@transaction.atomic
def resync_draft_batches(defaults=None):
    """Re-apply the current defaults to every DRAFT batch. Returns how many actually changed.

    A batch normally snapshots its configuration at creation and never re-reads it, so that an
    admin revising the org defaults cannot reshape a drive already underway. A DRAFT has not
    reached anyone though - no invitation exists for one (services.invites blocks sending on
    Draft), so nothing has been promised to a candidate and nothing has been sat. Leaving drafts
    frozen only produced the confusing case this exists to fix: change the defaults, create from
    an older draft, and get a configuration nobody currently sees on any screen.

    So: drafts track the defaults, everything else keeps its snapshot. The line is "have
    candidates been told about this exam yet", which is exactly what leaving Draft means.

    Overwrites a per-batch cutoff someone had revised on a draft. That is the intended reading
    of "drafts track the defaults" - and a draft's cutoffs have never graded anything, so there
    is no result the overwrite could invalidate.
    """
    from api.models import Batch, BatchSection

    defaults = defaults or get_batch_defaults()
    wanted = {s['section_id']: s for s in included_sections(defaults)}
    duration = defaults['exam_duration_minutes']

    changed = 0
    drafts = (
        Batch.objects.filter(status=Batch.Status.DRAFT, is_deleted=False)
        # Belt and braces. A Draft cannot have invitations today, but this is the condition the
        # whole rule rests on, so it is asserted here rather than assumed from another module's
        # behaviour staying the way it is.
        .exclude(invitation__isnull=False)
        .prefetch_related('sections')
    )
    for batch in drafts:
        touched = False

        if batch.exam_duration_minutes != duration:
            batch.exam_duration_minutes = duration
            batch.save(update_fields=['exam_duration_minutes'])
            touched = True

        existing = {bs.section_id: bs for bs in batch.sections.all()}

        removed = [bs.pk for section_id, bs in existing.items() if section_id not in wanted]
        if removed:
            BatchSection.objects.filter(pk__in=removed).delete()
            touched = True

        to_add, to_update = [], []
        for section_id, section in wanted.items():
            row = existing.get(section_id)
            if row is None:
                to_add.append(BatchSection(
                    batch=batch, section_id=section_id,
                    question_count=section['question_count'], cutoff=section['cutoff'],
                ))
            elif (row.question_count != section['question_count']
                    or float(row.cutoff) != float(section['cutoff'])):
                row.question_count = section['question_count']
                row.cutoff = section['cutoff']
                to_update.append(row)

        if to_add:
            BatchSection.objects.bulk_create(to_add)
            touched = True
        if to_update:
            BatchSection.objects.bulk_update(to_update, ['question_count', 'cutoff'])
            touched = True

        changed += bool(touched)
    return changed


def save_batch_defaults(values, user):
    """Persist the Configure Default Batch form.

    `values['sections']` is a list of {section_key, question_count, cutoff, included}. A section
    the caller omits is left exactly as it was rather than reset - the form only ever submits the
    sections it rendered, and silently zeroing one it never showed would be a change nobody made.

    An EXCLUDED section keeps its stored question count and cutoff rather than having them
    cleared, so re-ticking it restores what was configured before instead of silently resetting
    it to the fallback.
    """
    for name in GENERAL_KEYS:
        if name not in values:
            continue
        _write(_setting_key(name), values[name], user)

    for section in values.get('sections') or []:
        section_key = section['section_key']
        _write(_section_setting_key(section_key, 'questions'), section['question_count'], user)
        _write(_section_setting_key(section_key, 'cutoff'), section['cutoff'], user)
        _write(_section_setting_key(section_key, 'included'),
               bool(section.get('included', True)), user)


def _write(setting_key, value, user):
    Setting.objects.update_or_create(
        setting_key=setting_key,
        defaults={
            'setting_value': str(value),
            'setting_group': SETTING_GROUP,
            'updated_by': user,
        },
    )
