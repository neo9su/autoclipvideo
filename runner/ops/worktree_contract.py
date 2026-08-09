from __future__ import annotations

import os
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path


class WorktreeContractError(ValueError):
    """Raised when a worker is outside its assigned worktree contract."""


@dataclass(frozen=True)
class PreflightEvidence:
    """Machine-readable proof that a worker can safely start."""

    ok: bool
    checks: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "checks": list(self.checks)}

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)


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
        if actual_cwd == self.repo_root.resolve():
            raise WorktreeContractError("worker must not run in the main checkout")
        if not actual_cwd.is_dir() or not os.access(actual_cwd, os.W_OK):
            raise WorktreeContractError("assigned worktree is not writable")

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

    def preflight(self, cwd: str | Path | None = None) -> PreflightEvidence:
        """Return structured checks without widening the worktree boundary."""
        target = Path(cwd or self.worktree)
        checks: list[dict[str, object]] = []
        resolved = target.resolve()
        root = self.repo_root.resolve()
        expected = self.worktree.resolve()
        checks.append({"name": "worktree_allowlist", "ok": resolved == expected or expected in resolved.parents})
        checks.append({"name": "main_checkout_rejected", "ok": resolved != root})
        checks.append({"name": "writable", "ok": resolved.is_dir() and os.access(resolved, os.W_OK)})
        try:
            actual_root, actual_branch = discover_git_identity(resolved)
            checks.append({"name": "repository_identity", "ok": Path(actual_root).resolve() == root})
            checks.append({"name": "branch_identity", "ok": actual_branch == self.branch})
        except (OSError, WorktreeContractError) as exc:
            checks.append({"name": "identity", "ok": False, "error": str(exc)})
        return PreflightEvidence(all(bool(item.get("ok")) for item in checks), tuple(checks))

    def require_preflight(self, cwd: str | Path | None = None) -> PreflightEvidence:
        evidence = self.preflight(cwd)
        if not evidence.ok:
            raise WorktreeContractError(evidence.as_json())
        return evidence


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
