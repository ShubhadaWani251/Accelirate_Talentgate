from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import Question
from api.serializers.question import normalize_question_text


class Command(BaseCommand):
    """Collapse duplicate questions down to one row each.

    Duplicates are matched the same way the add/upload guards match them: normalised text
    (case-folded, whitespace collapsed), bank-wide. The lowest question_id in each group is
    kept as the original and the rest are deleted.

    Dry-run by default - deleting question rows is not reversible, so the destructive form has
    to be asked for explicitly with --apply.
    """
    help = 'Report (or with --apply, remove) duplicate questions in the question bank.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually delete the duplicates. Without this, only reports.')

    def _safe(self, text):
        """Question text can hold characters the console encoding can't represent (a rupee
        sign killed this command on a cp1252 Windows terminal). Report readability isn't worth
        a crash, so unmappable characters degrade to '?'.
        """
        encoding = getattr(self.stdout, 'encoding', None) or 'utf-8'
        return str(text).encode(encoding, errors='replace').decode(encoding, errors='replace')

    def handle(self, *args, **options):
        groups = defaultdict(list)
        for q in Question.objects.select_related('section').order_by('question_id'):
            groups[normalize_question_text(q.question_text)].append(q)

        duplicate_groups = {k: v for k, v in groups.items() if len(v) > 1}
        doomed = [q for rows in duplicate_groups.values() for q in rows[1:]]

        total = Question.objects.count()
        self.stdout.write(f'{total} question(s) in the bank, {len(groups)} distinct.')
        self.stdout.write(f'{len(duplicate_groups)} question(s) have duplicates; '
                          f'{len(doomed)} row(s) would be removed.\n')

        for rows in list(duplicate_groups.values())[:15]:
            keep = rows[0]
            self.stdout.write(self._safe(
                f'  keep {keep.question_code} [{keep.section.section_name}] '
                f'"{keep.question_text[:52]}..." '
                f'-> drop {len(rows) - 1}: {", ".join(r.question_code for r in rows[1:][:6])}'
                f'{" ..." if len(rows) - 1 > 6 else ""}'
            ))
        if len(duplicate_groups) > 15:
            self.stdout.write(f'  ... and {len(duplicate_groups) - 15} more group(s)')

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                '\nDry run - nothing deleted. Re-run with --apply to remove them.'))
            return

        if not doomed:
            self.stdout.write(self.style.SUCCESS('\nNothing to remove.'))
            return

        with transaction.atomic():
            deleted, _ = Question.objects.filter(
                question_id__in=[q.question_id for q in doomed]
            ).delete()
        self.stdout.write(self.style.SUCCESS(
            f'\nRemoved {len(doomed)} duplicate question(s). '
            f'{Question.objects.count()} remain.'))
