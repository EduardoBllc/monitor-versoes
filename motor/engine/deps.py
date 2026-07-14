"""Porte de internal/engine/deps.go."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo, TaskSource


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
