#!/usr/bin/env bash
# Read-only helper — ไม่ train, ไม่แก้ main, ไม่แตะ Gate
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

echo "=============================================="
echo " ZYRQUEN Phase B — read-only status"
echo "=============================================="
echo "cwd: $(pwd)"
echo "branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)"
echo "head: $(git log -1 --format='%h %s' 2>/dev/null | cut -c1-70 || echo n/a)"
echo

echo "== Pilot1 artifacts =="
for f in pilot1_result.json run_config.final.json run_pilot1.py zyrquen_RUN_20261122-pilot1.zip; do
  if [[ -f "$f" ]]; then
    sz=$(wc -c < "$f" | tr -d ' ')
    printf "  OK  %-40s %s bytes\n" "$f" "$sz"
  else
    printf "  --  %-40s (missing)\n" "$f"
  fi
done
echo

echo "== Gate verdict =="
if [[ -f pilot1_result.json ]]; then
  python3 -c 'import json;d=json.load(open("pilot1_result.json",encoding="utf-8"));print("  verdict   :",d.get("verdict"));print("  error_code:",d.get("error_code"));print("  summary   :",str(d.get("summary",""))[:80])'
else
  echo "  (no pilot1_result.json)"
fi
echo

echo "== Observability spec =="
SPEC="docs/v11/TRAINING_UPDATE_OBSERVABILITY_SPEC.md"
if [[ -f "$SPEC" ]]; then
  echo "  FOUND \( SPEC ( \)(wc -l < "$SPEC") lines)"
else
  echo "  MISSING $SPEC"
fi
echo

echo "== Nested clone =="
if [[ -d ../zyrquen-platform-nested-clone ]]; then
  echo "  moved OK -> ../zyrquen-platform-nested-clone"
else
  echo "  (no nested clone dir outside repo)"
fi
echo

echo "== Git status =="
git status -s 2>/dev/null | head -n 20 || echo "  (not a git repo?)"
echo
echo "Done. (read-only)"
