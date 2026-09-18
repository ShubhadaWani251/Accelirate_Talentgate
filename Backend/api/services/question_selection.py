"""Random per-candidate question assignment for the exam-taking portal.

Each candidate gets an independent random subset of Active questions per section, sized per
the batch's own configured counts - this is what "reduces answer-sharing within a batch's open
window" (SECTION_ORDER, `ExamAnswer` rows created from this sit for the rest of the attempt as
both the assignment and the answer sheet, see services/exam_session.py).

WHICH questions a candidate gets is random. HOW HARD their paper is, is not: the sample is
stratified by difficulty so every candidate drawing from the same bank gets the same number of
Easy, Medium and Hard questions per section. Previously this sampled uniformly from the whole
section pool, so with a bank holding (say) 28 Easy and 18 Medium verbal questions, one
candidate could draw an all-Easy paper and another a mostly-Medium one - and both were then
judged against the same cutoff. Two people sitting the same assessment on the same day were not
being asked an equivalent question.
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


# Apportionment order, which is also how ties are broken when two difficulties have the same
# fractional remainder. Fixed rather than derived from the data so the quota for a given bank is
# reproducible - the whole point is that every candidate gets the SAME difficulty counts.
DIFFICULTY_ORDER = [
    Question.Difficulty.EASY,
    Question.Difficulty.MEDIUM,
    Question.Difficulty.HARD,
]
# Tie-break rank. A dict with a default rather than DIFFICULTY_ORDER.index(), which raises on
# anything not in the list: a single row carrying an off-choices difficulty (inserted straight
# into the database, or left behind by a future rename) would otherwise crash paper selection -
# and that runs when a candidate presses Start, so the whole exam would be unreachable rather
# than merely unbalanced. Unknown values sort last and are still drawn from normally.
DIFFICULTY_RANK = {difficulty: i for i, difficulty in enumerate(DIFFICULTY_ORDER)}


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


def difficulty_quotas(pool_sizes, required):
    """How many of `required` questions to draw from each difficulty, in proportion to how many
    ACTIVE ones the bank holds at that difficulty. Returns {difficulty: count}.

    Largest-remainder (Hare quota) apportionment, done entirely in integer arithmetic: floats
    would make the split depend on binary rounding, and this number has to be identical for
    every candidate drawing from an unchanged bank, not merely close.

    Proportional to the POOL rather than to a fixed house ratio (say 40/40/20) on purpose -
    a fixed ratio is a policy nobody here has set, and it would fail outright against the real
    bank, which currently holds no Hard questions at all. Mirroring the pool needs no such
    decision and still delivers the thing that was actually broken: two candidates in one batch
    getting comparable papers.

    `pool_sizes` only contains difficulties that have at least one question, so a difficulty the
    bank doesn't stock simply never gets a quota.
    """
    total = sum(pool_sizes.values())
    quota = {d: required * n // total for d, n in pool_sizes.items()}
    # Whole quotas rarely sum to `required`; the leftover seats go to the difficulties with the
    # largest fractional parts. `required * n % total` IS that fractional part, scaled by
    # `total` - comparing the scaled values avoids the division entirely.
    shortfall = required - sum(quota.values())
    by_remainder = sorted(
        pool_sizes,
        key=lambda d: (-(required * pool_sizes[d] % total),
                       DIFFICULTY_RANK.get(d, len(DIFFICULTY_RANK))),
    )
    for difficulty in by_remainder[:shortfall]:
        quota[difficulty] += 1
    # No quota can exceed its pool: required <= total (the caller checks), so the floor above is
    # at most n, and it can only EQUAL n when required == total - in which case every remainder
    # is zero and no seat is handed out here. So random.sample below can never over-draw.
    return quota


def select_questions_for_attempt(batch):
    """Returns {section_key: [Question, ...]}, one difficulty-stratified random sample per
    configured section.

    Sampling picks random IDs in Python over an indexed id-only query rather than an SQL
    `ORDER BY RANDOM()`, which would force a full sort of the section's question pool on every
    call as the bank grows. The `(section, status, difficulty)` index on Question is what keeps
    the id-only query cheap now that difficulty comes back with it.
    """
    result = {}
    for section_key in SECTION_ORDER:
        required = getattr(batch, f'{section_key}_questions')
        if required <= 0:
            result[section_key] = []
            continue

        ids_by_difficulty = {}
        for question_id, difficulty in Question.objects.filter(
            section__section_key=section_key,
            status=Question.Status.ACTIVE,
        ).values_list('question_id', 'difficulty'):
            ids_by_difficulty.setdefault(difficulty, []).append(question_id)

        available = sum(len(ids) for ids in ids_by_difficulty.values())
        if available < required:
            raise InsufficientQuestionsError(section_key, required, available)

        quota = difficulty_quotas(
            {d: len(ids) for d, ids in ids_by_difficulty.items()}, required,
        )
        chosen_ids = [
            qid
            for difficulty, count in quota.items()
            for qid in random.sample(ids_by_difficulty[difficulty], k=count)
        ]
        # Shuffled AFTER the per-difficulty draws, so the paper isn't served in difficulty
        # blocks - every Easy question first would both telegraph the stratification and make
        # the back half of each section feel like a wall.
        random.shuffle(chosen_ids)

        questions_by_id = Question.objects.in_bulk(chosen_ids)
        # chosen_ids' order is the shuffle candidates see - re-fetching by id would otherwise
        # come back in the model's default `question_code` ordering (Meta.ordering).
        result[section_key] = [questions_by_id[qid] for qid in chosen_ids]
    return result
