from __future__ import annotations

import os
import subprocess
import tempfile
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

    def validate(self, cwd: str | Path, repo_root: str | Path, branch: str) -> None:
        actual_cwd = Path(cwd).resolve()
        expected = self.worktree.resolve()
        if actual_cwd != expected and expected not in actual_cwd.parents:
            raise WorktreeContractError("worker cwd is outside the assigned worktree")
        if Path(repo_root).resolve() != self.repo_root.resolve():
            raise WorktreeContractError("worker repo root does not match the contract")
        if branch != self.branch:
            raise WorktreeContractError("worker branch does not match the contract")

    def preflight(self, cwd: str | Path, repo_root: str | Path, branch: str,
                  expected_base: str | None = None) -> dict[str, object]:
        """Return sanitized evidence and fail closed on contract violations."""
        self.validate_allowlist(cwd, repo_root, branch)
        actual = Path(cwd).resolve()
        if actual.is_symlink() or any(part.is_symlink() for part in [actual, *actual.parents]):
            raise WorktreeContractError("worker worktree contains a symlink escape")
        if not os.access(actual, os.W_OK):
            raise WorktreeContractError("worker worktree is not writable")
        if expected_base:
            current = subprocess.check_output(["git", "-C", str(actual), "merge-base", "HEAD", expected_base], text=True).strip()
            if not current:
                raise WorktreeContractError("worker base cannot be verified")
        marker = actual / ".fabrica-preflight"
        try:
            marker.write_text("ok\n", encoding="utf-8")
            marker.unlink()
        except OSError as exc:
            raise WorktreeContractError("worker worktree cannot create temporary evidence") from exc
        return {"ok": True, "repo_root": str(self.repo_root), "worktree": str(actual), "branch": self.branch, "tool_profile": self.profile}

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
            "protocol_version": "1",
            "nonce": __import__("secrets").token_hex(16),
            "expected_branch": self.branch,
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
