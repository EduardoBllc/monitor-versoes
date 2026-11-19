"""Host GitLab do monitor-versoes: fonte de tarefas (GitLab Issues) e de PR."""

from monitor_versoes_gitlab.fonte import FonteGitlab
from monitor_versoes_gitlab.prs import GitlabPrs

__all__ = ["FonteGitlab", "GitlabPrs"]
