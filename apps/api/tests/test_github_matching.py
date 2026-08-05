"""
Tests for the heuristic GitHub-activity → task matcher
(services/github_matching.py).

Pure functions over plain values, so these run with no database, no fixtures
and no mocks — the same posture as the roadmap-shape validator tests. The
cases that matter most are the *negative* ones: this matcher's output feeds a
"your roadmap has drifted" signal, so a confident wrong match is worse than no
match at all.
"""

from src.services.github_matching import (
    MIN_MARGIN,
    TaskCandidate,
    best_match,
    normalize_tokens,
    score_candidates,
)


def _task(task_id, title, *, description=None, github_path=None):
    return TaskCandidate(
        task_id=task_id,
        short_id=f"AOS-{task_id}",
        title=title,
        description=description,
        github_path=github_path,
    )


# ─── normalize_tokens ────────────────────────────────────────────────────────
class TestNormalizeTokens:
    def test_splits_prose_branches_and_paths_alike(self):
        assert normalize_tokens("Add refresh endpoint") >= {"refresh", "endpoint"}
        assert normalize_tokens("feat/auth-refresh_v2") >= {"auth", "refresh"}
        assert normalize_tokens("apps/api/src/auth.py") >= {"auth", "api", "app"}

    def test_splits_camel_case(self):
        assert {"refresh", "token"} <= normalize_tokens("refreshToken")

    def test_drops_stopwords_and_generic_dev_vocabulary(self):
        # Every one of these is filler that would otherwise pad the overlap
        # count towards the two-token minimum on pure noise.
        assert normalize_tokens("fix the tests for this feature") == set()

    def test_stopwords_survive_depluralization(self):
        """Regression: `_singularize` used to run first and turn "this" into
        "thi", which no longer matched the stopword list and leaked through as
        a meaningless token that padded every overlap count."""
        assert normalize_tokens("this") == set()
        assert normalize_tokens("changes files versions") == set()

    def test_drops_short_tokens(self):
        assert normalize_tokens("a id ui go") == set()

    def test_collapses_plurals_but_not_double_s(self):
        assert normalize_tokens("endpoints") == normalize_tokens("endpoint")
        assert "acces" not in normalize_tokens("access")

    def test_handles_none_and_empty(self):
        assert normalize_tokens(None, "", None) == set()


# ─── scoring ─────────────────────────────────────────────────────────────────
class TestScoreCandidates:
    def test_returns_empty_for_no_tasks(self):
        assert score_candidates(message="anything", branch=None, changed_paths=[], tasks=[]) == []

    def test_ranks_the_vocabulary_match_first(self):
        tasks = [
            _task("1", "Implement JWT refresh token endpoint"),
            _task("2", "Design the pricing page layout"),
        ]
        scored = score_candidates(
            message="Implement the JWT refresh token endpoint",
            branch=None,
            changed_paths=[],
            tasks=tasks,
        )
        assert scored[0].task_id == "1"
        assert scored[0].score > scored[1].score

    def test_common_vocabulary_is_discounted(self):
        """A word every task shares can't identify which task a commit is for.

        Both tasks say "endpoint"; only one says "webhook". A commit mentioning
        just "endpoint" must not out-score on that alone.
        """
        tasks = [
            _task("1", "Build the webhook endpoint"),
            _task("2", "Build the billing endpoint"),
            _task("3", "Build the search endpoint"),
        ]
        scored = score_candidates(
            message="Build the webhook endpoint",
            branch=None,
            changed_paths=[],
            tasks=tasks,
        )
        assert scored[0].task_id == "1"
        # "endpoint" appears in all three, so the two non-webhook tasks are left
        # with essentially nothing.
        assert scored[1].score == 0.0

    def test_ordering_is_deterministic_on_ties(self):
        tasks = [_task("b", "Alpha beta gamma"), _task("a", "Alpha beta gamma")]
        first = score_candidates(message="alpha beta gamma", branch=None, changed_paths=[], tasks=tasks)
        second = score_candidates(message="alpha beta gamma", branch=None, changed_paths=[], tasks=list(reversed(tasks)))
        assert [c.task_id for c in first] == [c.task_id for c in second]

    def test_path_tokens_contribute_when_the_message_is_useless(self):
        tasks = [
            _task("1", "Harden the authentication middleware"),
            _task("2", "Write the marketing landing page"),
        ]
        scored = score_candidates(
            message="wip",
            branch=None,
            changed_paths=["apps/api/src/authentication/middleware.py"],
            tasks=tasks,
        )
        assert scored[0].task_id == "1"
        assert scored[0].score > 0

    def test_github_path_prefix_adds_a_bonus(self):
        without = score_candidates(
            message="Tidy the parser internals",
            branch=None,
            changed_paths=["apps/api/src/parser/lexer.py"],
            tasks=[_task("1", "Tidy the parser internals")],
        )[0]
        with_path = score_candidates(
            message="Tidy the parser internals",
            branch=None,
            changed_paths=["apps/api/src/parser/lexer.py"],
            tasks=[_task("1", "Tidy the parser internals", github_path="apps/api/src/parser")],
        )[0]
        assert with_path.score >= without.score

    def test_score_never_exceeds_one(self):
        scored = score_candidates(
            message="parser lexer tokenizer grammar",
            branch="feat/parser-lexer",
            changed_paths=["apps/api/src/parser/lexer.py"],
            tasks=[_task("1", "Parser lexer tokenizer grammar", github_path="apps/api/src/parser")],
        )
        assert scored[0].score <= 1.0

    def test_single_shared_token_alone_scores_nothing(self):
        scored = score_candidates(
            message="Touch the parser",
            branch=None,
            changed_paths=[],
            tasks=[_task("1", "Parser rewrite with incremental reparsing support")],
        )
        assert scored[0].score == 0.0


# ─── acceptance ──────────────────────────────────────────────────────────────
class TestBestMatch:
    def test_accepts_a_clear_winner(self):
        tasks = [
            _task("1", "Implement JWT refresh token rotation"),
            _task("2", "Write the onboarding welcome email"),
        ]
        match = best_match(
            message="Implement JWT refresh token rotation",
            branch="feat/jwt-refresh-rotation",
            changed_paths=[],
            tasks=tasks,
        )
        assert match is not None
        assert match.task_id == "1"
        assert 0 < match.score <= 1.0

    def test_rejects_a_near_tie(self):
        """The case that motivates the margin rule.

        "Add login endpoint" and "Add logout endpoint" against a commit that
        could be either must resolve to no match and fall through to the
        classifier — never to an arbitrary pick.
        """
        tasks = [
            _task("1", "Add the login endpoint to the auth router"),
            _task("2", "Add the logout endpoint to the auth router"),
        ]
        assert best_match(
            message="Add the endpoint to the auth router",
            branch=None,
            changed_paths=[],
            tasks=tasks,
        ) is None

    def test_rejects_when_nothing_clears_the_floor(self):
        tasks = [_task("1", "Implement JWT refresh token rotation")]
        assert best_match(
            message="Bump dependency versions",
            branch="chore/deps",
            changed_paths=[],
            tasks=tasks,
        ) is None

    def test_returns_none_for_no_candidates(self):
        assert best_match(message="anything", branch=None, changed_paths=[], tasks=[]) is None

    def test_single_candidate_still_has_to_clear_the_floor(self):
        """With one task there is no runner-up, so only MIN_SCORE guards it."""
        assert best_match(
            message="unrelated chore work",
            branch=None,
            changed_paths=[],
            tasks=[_task("1", "Implement JWT refresh token rotation")],
        ) is None

    def test_margin_constant_is_actually_enforced(self):
        """Guards against MIN_MARGIN being silently set to 0."""
        assert MIN_MARGIN > 0
