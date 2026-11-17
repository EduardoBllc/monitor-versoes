"""Host GitHub do monitor-versoes: fonte de tarefas (GitHub Issues) e de PR."""

from monitor_versoes_github.fonte import FonteGithub
from monitor_versoes_github.prs import GithubPrs

__all__ = ["FonteGithub", "GithubPrs"]
