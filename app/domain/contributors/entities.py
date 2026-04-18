from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GitHubLogin:
    value: str

    def __post_init__(self):
        if not self.value or not self.value.strip():
            raise ValueError("GitHub login cannot be empty")


@dataclass
class ContributorProfile:
    login: GitHubLogin
    avatar_url: str
    html_url: str


@dataclass
class CommitActivity:
    total_commits: int = 0
    lines_added: int = 0
    lines_deleted: int = 0
    weeks_active: int = 0

    @property
    def net_lines(self) -> int:
        return self.lines_added - self.lines_deleted


@dataclass
class PullRequestActivity:
    opened: int = 0
    merged: int = 0

    @property
    def merge_rate(self) -> float:
        return self.merged / self.opened if self.opened > 0 else 0.0


# ── Knowledge Sharer axis ─────────────────────────────────────────────────────

@dataclass
class KnowledgeSharerActivity:
    reviews_total: int = 0                  # total formal reviews (APPROVED / CHANGES_REQUESTED)
    meaningful_comments: int = 0            # review comments > 30 chars, not trivial
    cross_subsystem_prs: int = 0            # PRs where reviewer touched 2+ top-level dirs

    @property
    def total_weighted(self) -> float:
        return (
            self.reviews_total * 3.0
            + self.meaningful_comments * 1.5
            + self.cross_subsystem_prs * 5.0
        )


@dataclass
class Contributor:
    profile: ContributorProfile
    commit_activity: CommitActivity = field(default_factory=CommitActivity)
    pr_activity: PullRequestActivity = field(default_factory=PullRequestActivity)
    knowledge_sharer: KnowledgeSharerActivity = field(default_factory=KnowledgeSharerActivity)

    @property
    def login(self) -> str:
        return self.profile.login.value
