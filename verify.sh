#!/bin/bash
# verify.sh — Verification script for home-agent
# Run by autodev after each Sonnet implementation attempt.
# All checks must pass (exit 0) before moving to Opus review.
# Exit code 0 = success, non-zero = failure

set -e

# Ensure src/ is on the Python path for import-linter
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(pwd)/src"

echo "🔍 Running verification checks..."

# ── Type checking (ty) ────────────────────────────────────────────────────────
echo ""
echo "  ▸ Type checker (ty)..."
uv run ty check src/

# ── Import architecture linting ───────────────────────────────────────────────
echo ""
echo "  ▸ Import linter (architecture contracts)..."
uv run lint-imports

# ── Tests ─────────────────────────────────────────────────────────────────────
echo ""
echo "  ▸ Tests (pytest)..."
uv run pytest tests/ -q

echo ""
echo "✅ All checks passed!"
