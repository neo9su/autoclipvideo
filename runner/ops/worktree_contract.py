"""Trusted developer worktree contract used by the durable runner.

The contract is intentionally local and allow-list based: a worker may only run in
an explicitly assigned worktree beneath an approved repository root.  It does not
change global sandbox settings or grant access to the main checkout.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorktreeContractError(ValueError):
    """Raised when a worker execution context is outside its assigned worktree."""


@dataclass(frozen=True)
class WorktreeProfile:
    assigned_worktree: Path
    allowed_repo_root: Path

    def validate(self, cwd: str | Path | None = None) -> dict[str, str]:
        worktree = self.assigned_worktree.resolve()
        repo_root = self.allowed_repo_root.resolve()
        candidate = Path(cwd or worktree).resolve()
        if candidate != worktree:
            raise WorktreeContractError("worker cwd is not the assigned worktree")
        if worktree == repo_root or repo_root not in worktree.parents:
            raise WorktreeContractError("assigned worktree is outside the repository allowlist")
        if not worktree.is_dir():
            raise WorktreeContractError("assigned worktree does not exist")
        git = ["git", "-C", str(worktree)]
        try:
            root = subprocess.check_output(git + ["rev-parse", "--show-toplevel"], text=True).strip()
            branch = subprocess.check_output(git + ["branch", "--show-current"], text=True).strip()
            head = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise WorktreeContractError("assigned worktree is not a usable git worktree") from exc
        if Path(root).resolve() != worktree:
            raise WorktreeContractError("git root does not match assigned worktree")
        if not branch or not head:
            raise WorktreeContractError("worker must report a branch and head SHA")
        return {"cwd": str(worktree), "repo_root": root, "branch": branch, "head_sha": head}
