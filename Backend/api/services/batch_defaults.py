from api.models import Setting

SETTING_GROUP = 'exam_config'

# key -> (Batch field name it seeds, python type for parsing the stored string value)
DEFAULT_KEYS = {
    'exam_duration_minutes': int,
    'logical_questions': int,
    'quantitative_questions': int,
    'verbal_questions': int,
    'programming_questions': int,
    'logical_cutoff': float,
    'quantitative_cutoff': float,
    'verbal_cutoff': float,
    'programming_cutoff': float,
}

FALLBACK_DEFAULTS = {
    'exam_duration_minutes': 45,
    'logical_questions': 10,
    'quantitative_questions': 10,
    'verbal_questions': 10,
    'programming_questions': 10,
    'logical_cutoff': 70.0,
    'quantitative_cutoff': 70.0,
    'verbal_cutoff': 70.0,
    'programming_cutoff': 70.0,
}


def _setting_key(name):
    return f'{SETTING_GROUP}.{name}'


def get_batch_defaults():
    rows = {
        row.setting_key: row.setting_value
        for row in Setting.objects.filter(setting_group=SETTING_GROUP)
    }
    result = {}
    for name, caster in DEFAULT_KEYS.items():
        raw = rows.get(_setting_key(name))
        result[name] = caster(raw) if raw is not None else FALLBACK_DEFAULTS[name]
    return result


def save_batch_defaults(values, user):
    for name in DEFAULT_KEYS:
        Setting.objects.update_or_create(
            setting_key=_setting_key(name),
            defaults={
                'setting_value': str(values[name]),
                'setting_group': SETTING_GROUP,
                'updated_by': user,
            },
        )
