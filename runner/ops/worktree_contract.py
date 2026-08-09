from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeContractError(ValueError):
    """Raised when a worker is outside its assigned worktree contract."""


@dataclass(frozen=True)
class WorktreeContract:
    worktree: Path
    repo_root: Path
    branch: str
    profile: str = "trusted-developer"

    def preflight(self, cwd: str | Path | None = None) -> dict[str, object]:
        """Fail closed with structured evidence before worker bootstrap."""
        actual = Path(cwd or self.worktree).resolve()
        try:
            root, branch = discover_git_identity(actual)
            self.validate_allowlist(actual, root, branch)
            if not os.access(actual, os.W_OK) or not self.profile.strip():
                raise WorktreeContractError("worktree preflight check failed")
            probe = actual / ".runner-write-probe"
            probe.write_text("preflight", encoding="utf-8")
            probe.unlink()
            return {"cwd": str(actual), "repo_root": root, "branch": branch, "profile": self.profile, "checks": {"git_identity": True, "allowlist": True, "writable": True, "tool_profile": True}}
        except (OSError, WorktreeContractError) as exc:
            raise WorktreeContractError("worktree preflight failed") from exc

    def validate(self, cwd: str | Path, repo_root: str | Path, branch: str) -> None:
        actual_cwd = Path(cwd).resolve()
        expected = self.worktree.resolve()
        if actual_cwd != expected and expected not in actual_cwd.parents:
            raise WorktreeContractError("worker cwd is outside the assigned worktree")
        if Path(repo_root).resolve() != self.repo_root.resolve():
            raise WorktreeContractError("worker repo root does not match the contract")
        if branch != self.branch:
            raise WorktreeContractError("worker branch does not match the contract")

    def validate_allowlist(self, cwd: str | Path, repo_root: str | Path, branch: str) -> None:
        """Reject the main checkout and unrelated sibling worktrees."""
        self.validate(cwd, repo_root, branch)
        actual_worktree = Path(cwd).resolve()
        if actual_worktree == self.repo_root.resolve():
            raise WorktreeContractError("worker must not run in the main checkout")
        if actual_worktree != self.worktree.resolve() and self.worktree.resolve() not in actual_worktree.parents:
            raise WorktreeContractError("worker worktree is outside the assigned allowlist")

    def bootstrap_payload(self, run_id: str, generation: int, cwd: str | Path | None = None) -> dict[str, object]:
        actual_cwd = Path(cwd or self.worktree).resolve()
        return {
            "run_id": run_id,
            "generation": generation,
            "cwd": str(actual_cwd),
            "repo_root": str(self.repo_root.resolve()),
            "branch": self.branch,
            "tool_profile": self.profile,
        }


def discover_git_identity(cwd: str | Path) -> tuple[str, str]:
    """Return repository root and branch without consulting ambient PATH state."""
    directory = str(Path(cwd).resolve())
    try:
        root = subprocess.check_output(["git", "-C", directory, "rev-parse", "--show-toplevel"], text=True).strip()
        branch = subprocess.check_output(["git", "-C", directory, "branch", "--show-current"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorktreeContractError("unable to identify git worktree") from exc
    if not root or not branch:
        raise WorktreeContractError("git worktree has no repository root or branch")
    return root, branch


def default_contract() -> WorktreeContract:
    cwd = Path.cwd().resolve()
    root, branch = discover_git_identity(cwd)
    return WorktreeContract(cwd, Path(root), branch, os.getenv("TASK_RUNNER_TOOL_PROFILE", "trusted-developer"))
