#!/usr/bin/env bash
# scripts/apply-patches.sh -- apply every tracked Torque3D patch, idempotently.
#
# third_party/Torque3D is git-ignored and disposable, so patches -- not hand
# edits -- are the only way upstream source changes survive a re-fetch. This
# script is safe to run repeatedly: a patch that is already applied is skipped,
# and a patch that neither applies nor is applied is a hard error (the pin or
# the patch is wrong, and silently continuing would build the wrong tree).
set -euo pipefail

T3D="${T3D:-third_party/Torque3D}"
PATCH_DIR="${PATCH_DIR:-patches/torque3d}"

if [ ! -d "$T3D/.git" ]; then
  echo "ERROR: $T3D is not a git checkout. Run scripts/fetch-torque3d.sh" >&2
  exit 1
fi

if [ ! -d "$PATCH_DIR" ]; then
  echo "no patch directory $PATCH_DIR; nothing to do"
  exit 0
fi

shopt -s nullglob
patches=("$PATCH_DIR"/*.patch)
shopt -u nullglob

if [ ${#patches[@]} -eq 0 ]; then
  echo "no patches in $PATCH_DIR; nothing to do"
  exit 0
fi

for p in "${patches[@]}"; do
  name="$(basename "$p")"
  # Absolute: `git -C "$T3D"` changes directory first, so a relative patch path
  # would be resolved inside the checkout instead of against the repo root.
  p="$(cd "$(dirname "$p")" && pwd)/$(basename "$p")"
  if git -C "$T3D" apply --check --reverse "$p" >/dev/null 2>&1; then
    echo "already applied: $name"
  elif git -C "$T3D" apply --check "$p" >/dev/null 2>&1; then
    git -C "$T3D" apply "$p"
    echo "applied: $name"
  else
    echo "ERROR: $name neither applies nor is applied -- the pin or the patch is wrong" >&2
    exit 1
  fi
done
