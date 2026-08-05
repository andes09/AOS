"""
Heuristic matching of GitHub activity to roadmap tasks — the fallback for when
nobody typed a `short_id`.

`integrations/github/events.py` links a commit or PR to a `Task` by finding an
exact "AOS-142" token in the branch name, commit message, or PR title. That is
the only path that may move a task's status, and it stays that way. But it
requires the developer to know and type the identifier, which a founder
driving an AI coding agent essentially never does — so without a second path,
every event is unmatched and any question about how much shipped work was on
the roadmap answers "none of it".

This module is that second path, and it is deliberately dumb: token overlap
plus file-path prefixes, no model call, no I/O, no ORM. Everything here is a
pure function over plain values so it unit-tests directly (same posture as
services/roadmap_shapes.py's validators), and so the expensive path — the LLM
classifier in services/github_classifier.py — only ever sees what this could
not resolve.

The scoring question is deliberately asymmetric: **"how much of this task's
distinctive vocabulary shows up in this commit?"**, not "how similar are these
two strings". A commit message is short, scoped, and full of boilerplate; a
task title is a curated description of one unit of work. Asking whether the
task's words appear in the commit survives the commit also mentioning five
other things, which the symmetric version does not.

Two guards keep this honest, because a wrong quiet match is worse here than no
match — it would tell a founder their roadmap is on track when it isn't:

  - **Distinctiveness.** Tokens are weighted by how rare they are across the
    candidate set (an inverse-document-frequency weight computed over the
    project's own tasks, not a corpus). In a roadmap where nine tasks say
    "endpoint", matching on "endpoint" tells you nothing, and the weighting
    says so without needing a hand-maintained stopword list per project.
  - **Margin.** A match is only accepted when the best candidate beats the
    runner-up by `MIN_MARGIN`. Two similar tasks ("Add login endpoint" / "Add
    logout endpoint") against an ambiguous commit must resolve to *no match*
    and fall through to the classifier, never to an arbitrary pick between
    two near-ties.
"""

import re
from dataclasses import dataclass
from math import log

# Score a candidate must reach before it is considered at all.
MIN_SCORE = 0.45
# ...and how far it must sit above the runner-up. Below this the two are
# treated as indistinguishable and nothing is matched.
MIN_MARGIN = 0.15
# A single shared word is a coincidence, not a signal — unless a changed file
# path independently corroborates it (see `_path_bonus`).
MIN_OVERLAP_TOKENS = 2
# Tokens shorter than this carry no meaning here ("a", "id", "ui" all lose to
# noise) and inflate overlap counts.
MIN_TOKEN_LENGTH = 3
# Ceiling on the path-match bonus, so a path hit strengthens a weak textual
# match but can never single-handedly manufacture one against the margin rule.
PATH_BONUS = 0.35

# English filler plus the vocabulary every commit message and task title in a
# software project shares. These words are individually harmless but they pad
# the overlap count towards MIN_OVERLAP_TOKENS on pure noise. The IDF weighting
# already discounts whatever is common *within a given roadmap*; this list
# handles the words that are common across all of them, which IDF computed over
# a handful of tasks cannot see.
_STOPWORDS = frozenset(
    """
    the and for with that this from into out off but not are was were will would
    can could should has have had its our your their they them then than when
    where which while about over under after before per via use used using
    add added adds update updated updates fix fixed fixes bug patch change
    changed changes tweak tweaks refactor refactored cleanup clean chore wip
    merge merged revert bump initial init setup set get make made new old
    work working works implement implemented implementing support supported
    create created creating remove removed removing delete deleted improve
    improved test tests testing spec specs code file files line lines version
    main master develop branch commit pull request pr feat feature docs doc
    build ci lint format style run runs running todo misc stuff things thing
    """.split()
)

# Splits on anything that isn't alphanumeric, which covers the three shapes
# these strings arrive in: prose ("Add the refresh endpoint"), branch/path
# segments ("feat/auth-refresh_v2", "apps/api/src/auth.py"), and camelCase is
# handled separately below since a naive split would keep "refreshToken" whole.
_WORD_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class TaskCandidate:
    """A roadmap task, flattened to just what matching needs.

    Deliberately not the ORM `Task`: keeping this module free of SQLAlchemy is
    what lets the scorer be tested with literals instead of a database, and
    stops a lazy-load from firing inside a scoring loop.
    """

    task_id: str
    short_id: str | None
    title: str
    description: str | None = None
    github_path: str | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    task_id: str
    score: float
    overlap: frozenset[str]


def _singularize(token: str) -> str:
    """Crude plural collapse so "endpoints" matches "endpoint".

    Not a stemmer on purpose — a real one pulls in a dependency and starts
    conflating words ("running" → "run" → matches "runtime"), which costs more
    precision here than the recall it buys.
    """
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalize_tokens(*texts: str | None) -> set[str]:
    """Lowercased, de-pluralized, meaningful tokens from arbitrary text.

    Accepts prose, branch names, and file paths interchangeably — all three get
    split the same way, since "feat/auth-refresh" and "auth refresh" should
    produce the same tokens.
    """
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        expanded = _CAMEL_SPLIT_RE.sub(" ", text)
        for raw in _WORD_SPLIT_RE.split(expanded):
            lowered = raw.lower()
            # Check the stopword list *before* de-pluralizing as well as after:
            # `_singularize` would turn "this" into "thi", which no longer
            # matches the list and would survive as a meaningless token. The
            # second check catches the reverse case ("changes" → "change").
            if lowered in _STOPWORDS:
                continue
            token = _singularize(lowered)
            if len(token) >= MIN_TOKEN_LENGTH and token not in _STOPWORDS:
                tokens.add(token)
    return tokens


def _idf_weights(task_token_sets: list[set[str]]) -> dict[str, float]:
    """Inverse document frequency over *this project's* tasks.

    A token appearing in every task carries no information about which task a
    commit belongs to; one appearing in a single task is close to a fingerprint.
    Smoothed so a token present in all N tasks still gets a small positive
    weight rather than exactly zero — otherwise a task whose every word is
    common would have a zero-weight denominator.
    """
    total = len(task_token_sets)
    if total == 0:
        return {}
    counts: dict[str, int] = {}
    for tokens in task_token_sets:
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    return {token: log(1 + total / count) for token, count in counts.items()}


def _path_bonus(changed_paths: list[str], github_path: str | None) -> float:
    """Corroboration from the files actually touched.

    `Task.github_path` is set when a task is scoped to a known area of the
    repo. A commit that edits inside that subtree is real evidence independent
    of any wording, which is exactly what a short, vague commit message lacks.
    """
    if not github_path or not changed_paths:
        return 0.0
    prefix = github_path.strip("/")
    if not prefix:
        return 0.0
    if any(path.strip("/").startswith(prefix) for path in changed_paths):
        return PATH_BONUS
    return 0.0


def score_candidates(
    *,
    message: str | None,
    branch: str | None,
    changed_paths: list[str] | None,
    tasks: list[TaskCandidate],
) -> list[ScoredCandidate]:
    """Score every task against one GitHub event, best first.

    The score is the share of a task's distinctive vocabulary (IDF-weighted)
    that appears in the event's text, plus a bounded bonus when the event
    touched files under the task's `github_path`. Capped at 1.0 so the bonus
    can't push a score out of range.
    """
    if not tasks:
        return []

    changed_paths = changed_paths or []
    # Paths contribute their own tokens too: a commit touching
    # "apps/api/src/auth.py" is about auth even when the message says "wip".
    event_tokens = normalize_tokens(message, branch, *changed_paths)

    task_token_sets = [normalize_tokens(t.title, t.description) for t in tasks]
    idf = _idf_weights(task_token_sets)

    scored: list[ScoredCandidate] = []
    for task, task_tokens in zip(tasks, task_token_sets):
        overlap = task_tokens & event_tokens
        bonus = _path_bonus(changed_paths, task.github_path)

        denominator = sum(idf.get(t, 0.0) for t in task_tokens)
        if denominator > 0:
            coverage = sum(idf.get(t, 0.0) for t in overlap) / denominator
        else:
            coverage = 0.0

        # One shared word is a coincidence. Let it count only when a path match
        # says the commit really did touch this task's area of the repo.
        if len(overlap) < MIN_OVERLAP_TOKENS and bonus == 0.0:
            coverage = 0.0

        scored.append(
            ScoredCandidate(
                task_id=task.task_id,
                score=min(1.0, coverage + bonus),
                overlap=frozenset(overlap),
            )
        )

    # Tie-break by task_id so the ordering is total and deterministic — two
    # equal scores must not depend on dict/query ordering, or the margin rule
    # below would accept or reject the same input differently across runs.
    scored.sort(key=lambda c: (-c.score, c.task_id))
    return scored


def best_match(
    *,
    message: str | None,
    branch: str | None,
    changed_paths: list[str] | None,
    tasks: list[TaskCandidate],
) -> ScoredCandidate | None:
    """The one confident match, or None.

    Returns None on an ambiguous field (two candidates within `MIN_MARGIN`)
    rather than picking the nominal winner — see the module docstring. The
    caller should treat None as "unmatched, hand it to the classifier", not as
    "no relationship exists".
    """
    scored = score_candidates(
        message=message, branch=branch, changed_paths=changed_paths, tasks=tasks
    )
    if not scored:
        return None

    top = scored[0]
    if top.score < MIN_SCORE:
        return None

    runner_up = scored[1].score if len(scored) > 1 else 0.0
    if top.score - runner_up < MIN_MARGIN:
        return None

    return top
