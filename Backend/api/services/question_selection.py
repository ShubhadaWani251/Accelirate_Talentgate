"""Random per-candidate question assignment for the exam-taking portal.

Each candidate gets an independent random subset of Active questions per section, sized per
the batch's own configured counts - this is what "reduces answer-sharing within a batch's open
window" (SECTION_ORDER, `ExamAnswer` rows created from this sit for the rest of the attempt as
both the assignment and the answer sheet, see services/exam_session.py).
"""

import random

from api.models import Question, QuestionBankSection

# Fixed in code, not a Batch field - the brief doesn't ask for configurable section order, and
# grouping ExamAnswer rows by insertion order (see exam_session.start_attempt) only needs one
# consistent constant here.
SECTION_ORDER = ['logical', 'quantitative', 'verbal', 'programming']

SECTION_LABELS = {
    'logical': 'Logical & Analytical',
    'quantitative': 'Quantitative',
    'verbal': 'Verbal Ability',
    'programming': 'Programming',
}


class InsufficientQuestionsError(Exception):
    """Raised when a section's Active question pool is smaller than the batch requires."""

    def __init__(self, section_key, required, available):
        self.section_key = section_key
        self.required = required
        self.available = available
        super().__init__(
            f"Section '{section_key}' needs {required} active questions but only "
            f"{available} are available."
        )


def select_questions_for_attempt(batch):
    """Returns {section_key: [Question, ...]}, one random sample per configured section.

    Sampling picks random IDs in Python over an indexed id-only query rather than an SQL
    `ORDER BY RANDOM()`, which would force a full sort of the section's question pool on every
    call as the bank grows.
    """
    result = {}
    for section_key in SECTION_ORDER:
        required = getattr(batch, f'{section_key}_questions')
        if required <= 0:
            result[section_key] = []
            continue

        ids = list(
            Question.objects.filter(
                section__section_key=section_key,
                status=Question.Status.ACTIVE,
            ).values_list('question_id', flat=True)
        )
        if len(ids) < required:
            raise InsufficientQuestionsError(section_key, required, len(ids))

        chosen_ids = random.sample(ids, k=required)
        questions_by_id = Question.objects.in_bulk(chosen_ids)
        # random.sample's own order is the shuffle candidates see - re-fetching by id would
        # otherwise come back in the model's default `question_code` ordering (Meta.ordering).
        result[section_key] = [questions_by_id[qid] for qid in chosen_ids]
    return result
