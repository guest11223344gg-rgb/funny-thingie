#!/usr/bin/env bash
# scripts/fetch-torque3d.sh — clone Torque3D at the pinned commit.
# Idempotent: if already at the pin, does nothing.
set -euo pipefail

REPO="https://github.com/TorqueGameEngines/Torque3D.git"
BRANCH="development"
DEST="third_party/Torque3D"
PIN_FILE="third_party/Torque3D.pin"
PIN="${TORQUE3D_PIN:-4c44642aab32cf79be4f66966d49fd74ab18e221}"

mkdir -p third_party

if [ -d "$DEST/.git" ]; then
  CURRENT=$(git -C "$DEST" rev-parse HEAD)
  if [ "$CURRENT" = "$PIN" ]; then
    echo "already at $PIN"
    echo "$PIN" > "$PIN_FILE"
    exit 0
  fi
  echo "checking out $PIN (was $CURRENT)"
  git -C "$DEST" fetch --depth 1 origin "$PIN"
  git -C "$DEST" checkout --detach "$PIN"
else
  echo "cloning $BRANCH"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DEST"
  CURRENT=$(git -C "$DEST" rev-parse HEAD)
  if [ "$CURRENT" != "$PIN" ]; then
    echo "NOTE: branch head is $CURRENT, pinning to $PIN instead"
    git -C "$DEST" fetch --depth 1 origin "$PIN"
    git -C "$DEST" checkout --detach "$PIN"
  fi
fi

git -C "$DEST" rev-parse HEAD > "$PIN_FILE"
echo "pinned at $(cat "$PIN_FILE")"
