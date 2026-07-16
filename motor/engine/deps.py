"""Porte de internal/engine/deps.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo, TaskSource


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
    lock_dir: str = ""
    bitbucket_token: str = ""  # se presente, PR do Bitbucket vira fonte primaria de commits
