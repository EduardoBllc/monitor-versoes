#!/bin/sh
# Salva base/ours/theirs + mensagem de merge/cherry-pick dos arquivos em conflito.
# Grava em <monitor-versoes>/conflitos/<hash-do-commit-theirs>.
# Uso: ./save-conflict-state.sh  (rodar de dentro do repo/worktree em conflito)
set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
gitdir="$(git rev-parse --git-dir)"

if [ -f "$gitdir/CHERRY_PICK_HEAD" ]; then
  hash=$(cat "$gitdir/CHERRY_PICK_HEAD")
elif [ -f "$gitdir/MERGE_HEAD" ]; then
  hash=$(cat "$gitdir/MERGE_HEAD")
else
  echo "Nenhum cherry-pick/merge em andamento." >&2
  exit 1
fi

files=$(git diff --name-only --diff-filter=U)
if [ -z "$files" ]; then
  echo "Nenhum arquivo em conflito." >&2
  exit 1
fi

outdir="$script_dir/conflitos/$hash"
mkdir -p "$outdir"

echo "$files" | while IFS= read -r p; do
  name=$(basename "$p")
  ext="${name##*.}"
  base="${name%.*}"
  git show ":1:$p" > "$outdir/${base}.base.${ext}" 2>/dev/null || true
  git show ":2:$p" > "$outdir/${base}.ours.${ext}"  2>/dev/null || true
  git show ":3:$p" > "$outdir/${base}.theirs.${ext}" 2>/dev/null || true
done

for f in MERGE_MSG COMMIT_EDITMSG; do
  [ -f "$gitdir/$f" ] && cp "$gitdir/$f" "$outdir/$f.txt"
done

echo "Salvo em $outdir"
