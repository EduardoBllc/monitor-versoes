"""Porte de internal/services/base_resolver_test.go."""

import datetime

from motor.adapters.git.fake import FakeGit
from motor.services.base_resolver import BaseResolver


def test_base_resolver_resolve():
    g = FakeGit()
    g.add_commit("hash136", "", "base 13.6.0", datetime.datetime.now(datetime.timezone.utc))
    g.set_branch("13.6.0", "hash136")

    resolver = BaseResolver(git=g)
    base = resolver.resolve("13.7.0")

    assert base.ref == "13.6.0" and base.commit == "hash136", f"base = {base!r}, quer ref=13.6.0 commit=hash136"
