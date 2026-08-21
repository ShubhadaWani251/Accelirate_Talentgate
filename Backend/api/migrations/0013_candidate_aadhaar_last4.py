"""Store only the last 4 digits of a candidate's Aadhaar number.

Ordering here is deliberate and must not be rearranged:

  1. Truncate the data FIRST. The column is varchar(255) holding 12-digit numbers; narrowing it
     to varchar(4) before truncating would make Postgres reject the ALTER COLUMN TYPE outright
     ("value too long for type character varying(4)").
  2. Drop the old index, because it is redefined against the renamed field.
  3. Rename, then narrow.

The truncation is IRREVERSIBLE - the leading digits are gone once this runs. That is the point
of the change (the platform has no use for a full Aadhaar number), but it means this migration
cannot be meaningfully unapplied, hence reverse_code=RunPython.noop rather than a fake inverse
that would silently leave 4-digit values in a 255-wide column.
"""

from django.db import migrations, models


def truncate_to_last4(apps, schema_editor):
    """Keep the last 4 characters of every stored value.

    Done in SQL rather than by iterating the queryset: this runs against every existing
    candidate row, and a per-row save would be one UPDATE each. RIGHT() is safe on shorter
    values (returns the whole string) and on empty ones.
    """
    schema_editor.execute(
        "UPDATE candidates "
        r"SET aadhaar_number = RIGHT(REGEXP_REPLACE(COALESCE(aadhaar_number, ''), '\D', '', 'g'), 4)"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0012_alter_candidate_validation_status'),
    ]

    operations = [
        migrations.RunPython(truncate_to_last4, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name='candidate',
            name='ix_candidates_aadhaar',
        ),
        migrations.RenameField(
            model_name='candidate',
            old_name='aadhaar_number',
            new_name='aadhaar_last4',
        ),
        migrations.AlterField(
            model_name='candidate',
            name='aadhaar_last4',
            field=models.CharField(
                help_text="Last 4 digits of the candidate's Aadhaar number. The full number is "
                          "never stored.",
                max_length=4,
            ),
        ),
        migrations.AddIndex(
            model_name='candidate',
            index=models.Index(fields=['aadhaar_last4'], name='ix_candidates_aadhaar'),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='validation_status',
            field=models.CharField(
                choices=[
                    ('ok', 'OK'),
                    ('missing_email', 'Missing Email'),
                    ('missing_aadhaar', 'Missing Aadhaar Last 4 Digits'),
                    ('missing_name', 'Missing Name'),
                    ('missing_college', 'Missing College'),
                    ('invalid_email', 'Invalid Email'),
                    ('duplicate_email', 'Duplicate Email'),
                    ('invalid_aadhaar', 'Invalid Aadhaar Last 4 Digits'),
                    ('duplicate_aadhaar', 'Duplicate Aadhaar Last 4 Digits'),
                    ('invalid_mobile', 'Invalid Mobile'),
                    ('invalid_text', 'Invalid Text Field'),
                    ('invalid_percentage', 'Invalid Percentage'),
                    ('invalid_year', 'Invalid Passing Year'),
                    ('missing_mobile', 'Missing Mobile'),
                    ('missing_degree', 'Missing Degree'),
                    ('missing_stream', 'Missing Stream'),
                    ('missing_percentage', 'Missing Percentage'),
                    ('missing_year', 'Missing Passing Out Year'),
                    ('missing_location', 'Missing Location'),
                ],
                default='ok', max_length=20,
            ),
        ),
    ]
