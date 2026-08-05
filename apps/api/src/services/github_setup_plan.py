"""
The fixed "Get set up with GitHub" milestone, for founders who told onboarding
they don't have GitHub yet (POST /github/needs-setup → OnboardingSession.
github_setup_needed_at).

Why this is hardcoded rather than a prompt instruction to the planner:

1. **Timing.** The roadmap is pre-generated in the background the moment the
   idea interview completes (onboarding_v2._maybe_prewarm_roadmap), which is
   *earlier* in the flow than the GitHub step. A prompt-only signal set on the
   GitHub step would therefore land after generation about half the time —
   the founder's plan would or wouldn't mention GitHub depending on how long
   they spent reading a screen. Injecting deterministically after the fact
   removes the race entirely.
2. **The planner doesn't know Omada.** The last and most important task here
   is connecting the repo to Omada so PR activity auto-completes tasks. No
   amount of prompting gets an LLM to describe a product it has never seen.

roadmap_generator._brief_prompt still tells the planner about the flag when it
happens to know in time, but only so it doesn't *duplicate* these tasks — the
milestone itself never depends on that.
"""

import logging
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.milestone import Milestone
from src.models.onboarding_session import OnboardingSession
from src.models.organization import Organization
from src.models.project import Project
from src.models.team import Team
from src.services.roadmap_shapes import _add_tasks
from src.services.task_ids import allocate_short_ids

logger = logging.getLogger(__name__)

# Doubles as the idempotency key — see ensure_github_setup_milestone. A title
# match is enough here because this milestone is ours, not the planner's, and
# _brief_prompt tells the planner not to produce anything like it.
MILESTONE_TITLE = "Get set up with GitHub"

MILESTONE_DESCRIPTION = (
    "You told us you haven't used GitHub before. GitHub is where your code "
    "lives, and it's also how Omada follows your progress — once it's "
    "connected, finishing work in GitHub ticks tasks off here automatically. "
    "This is a one-time setup: work through it once and it's done for the "
    "whole project."
)

# Shaped exactly like roadmap_shapes.validated_task's output so the normal
# persistence helper can be reused verbatim. All day_offset 0: this is the
# blocker in front of everything else, so it belongs on day one.
SETUP_TASKS: list[dict] = [
    {
        "title": "Create a free GitHub account",
        "description": (
            "Go to github.com/signup and create an account. Your username is "
            "public and shows up on everything you build, so pick something "
            "you'd be happy to put on a CV — your name or a simple handle "
            "beats a throwaway. Use an email address you actually check, "
            "then click the verification link GitHub sends you.\n\n"
            "Before you leave, turn on two-factor authentication under "
            "Settings → Password and authentication. GitHub requires it for "
            "anyone pushing code, so doing it now saves being locked out "
            "later."
        ),
        "day_offset": 0,
        "duration_minutes": 15,
    },
    {
        "title": "Install Git on your computer",
        "description": (
            "Git is the tool that tracks changes to your code; GitHub is the "
            "website that stores it. You need both.\n\n"
            "macOS: run `xcode-select --install`, or `brew install git` if "
            "you have Homebrew.\n"
            "Windows: download the installer from git-scm.com/download/win "
            "and accept every default — they're sensible.\n"
            "Linux: `sudo apt install git` (or your distro's equivalent).\n\n"
            "Open a new terminal window and run `git --version`. If it prints "
            "a version number, you're done. If it says command not found, "
            "close the terminal and open a fresh one first — the installer "
            "only affects terminals opened after it ran."
        ),
        "day_offset": 0,
        "duration_minutes": 20,
    },
    {
        "title": "Tell Git who you are",
        "description": (
            "Git stamps your name and email onto every change you save, so it "
            "refuses to do much until you've set them. Run these two "
            "commands, using the same email address you signed up to GitHub "
            "with so your work gets linked to your account:\n\n"
            "`git config --global user.name \"Your Name\"`\n"
            "`git config --global user.email \"you@example.com\"`\n\n"
            "Check it stuck with `git config --global --list`. This is a "
            "one-time setup per computer, not per project."
        ),
        "day_offset": 0,
        "duration_minutes": 10,
    },
    {
        "title": "Install the GitHub CLI and sign in",
        "description": (
            "The GitHub CLI (`gh`) handles logging in for you, which is what "
            "stops Git asking for a password every single time you push. "
            "Without it you'd be creating access tokens by hand.\n\n"
            "macOS: `brew install gh`\n"
            "Windows: `winget install --id GitHub.cli`\n"
            "Linux: follow the instructions at "
            "github.com/cli/cli/blob/trunk/docs/install_linux.md\n\n"
            "Then run `gh auth login` and choose: GitHub.com → HTTPS → yes, "
            "authenticate Git with your GitHub credentials → login with a web "
            "browser. Paste the code it shows you into the browser window it "
            "opens. Confirm with `gh auth status`."
        ),
        "day_offset": 0,
        "duration_minutes": 20,
    },
    {
        "title": "Create your project repository and push your first commit",
        "description": (
            "A repository ('repo') is one project's folder of code, with its "
            "full history. Make one for this project.\n\n"
            "From inside your project folder in the terminal:\n\n"
            "`git init`\n"
            "`git add .`\n"
            "`git commit -m \"First commit\"`\n"
            "`gh repo create --private --source=. --remote=origin --push`\n\n"
            "That last command creates the repo on GitHub and uploads what "
            "you have in one go. Start it private — you can flip it public "
            "later from the repo's settings.\n\n"
            "Open the repo on github.com afterwards and check your files are "
            "actually there. If you don't have a project folder yet, make an "
            "empty one with a README first; you can start committing real "
            "code into it as soon as the plan gets going."
        ),
        "day_offset": 0,
        "duration_minutes": 25,
    },
    {
        "title": "Connect GitHub to Omada",
        "description": (
            "Last step, and the one that pays off every day after this. In "
            "Omada, open Settings from the top bar, find the GitHub section, "
            "and click Connect GitHub. You'll be sent to GitHub to install "
            "the Omada app — choose the repo you just created rather than "
            "granting access to everything.\n\n"
            "Once it's connected, every task in your plan has a short ID like "
            "AOS-142 next to it. Put that ID in your branch name or pull "
            "request title and Omada marks the task done for you when the "
            "work lands, so your roadmap stays honest without you updating it "
            "by hand."
        ),
        "day_offset": 0,
        "duration_minutes": 15,
    },
]


async def ensure_github_setup_milestone(
    session: OnboardingSession, project: Project, db: AsyncSession
) -> bool:
    """Prepend the fixed GitHub-setup milestone to `project`, if it's wanted
    and isn't already there. Returns whether anything was added.

    Idempotent and safe to call on every path that produces or first shows a
    roadmap — generation, regeneration, and the plan-review step's read of an
    already-generated (pre-warmed or imported) plan.

    The caller commits, matching roadmap_shapes.create_project_with_milestones.
    """
    if session.github_setup_needed_at is None:
        return False

    # Also autoflushes anything the caller has pending, so the sort_order
    # UPDATE below sees rows rather than in-memory objects.
    existing = await db.scalar(
        select(func.count(Milestone.id)).where(
            Milestone.project_id == project.id,
            Milestone.title == MILESTONE_TITLE,
        )
    )
    if existing:
        return False

    # Make room at position 0. synchronize_session=False because the caller
    # commits immediately after, which expires every in-memory Milestone
    # anyway — and "evaluate" can't be trusted to match rows this statement
    # touched but the session never loaded.
    await db.execute(
        update(Milestone)
        .where(Milestone.project_id == project.id)
        .values(sort_order=Milestone.sort_order + 1)
        .execution_options(synchronize_session=False)
    )

    milestone = Milestone(
        project_id=project.id,
        title=MILESTONE_TITLE,
        description=MILESTONE_DESCRIPTION,
        sort_order=0,
    )
    db.add(milestone)
    await db.flush()  # assign milestone.id

    team = await db.get(Team, project.team_id)
    org = await db.get(Organization, team.organization_id)
    short_ids = await allocate_short_ids(org, len(SETUP_TASKS), db)
    _add_tasks(milestone.id, SETUP_TASKS, date.today(), short_ids, db)

    logger.info(
        "[github-setup] prepended setup milestone to project %s (session %s)",
        project.id,
        session.id,
    )
    return True
