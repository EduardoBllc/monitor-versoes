import os, subprocess, sys, tempfile, time
from pathlib import Path
from motor.adapters.estado.engine import garantir_esquema

for raiz in sys.argv[1:]:
    base = Path(tempfile.mkdtemp(dir=raiz))
    t = time.perf_counter()
    for i in range(5):
        garantir_esquema(f"sqlite:///{base / f'e{i}.db'}")
    mig = (time.perf_counter() - t) / 5
    repo = base / "r"; repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@a", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@a"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    t = time.perf_counter()
    for i in range(30):
        (repo / f"f{i}").write_text(str(i))
        subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", str(i)], cwd=repo, check=True, env=env)
    git = (time.perf_counter() - t) / 30
    print(f"{raiz}: migracao {mig:.2f}s, commit git {git*1000:.0f}ms", flush=True)
