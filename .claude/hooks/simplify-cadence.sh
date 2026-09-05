#!/usr/bin/env bash
#
# Threshold-gated code-simplifier cadence.
#
# Claude Code runs this as a Stop hook. It measures how many source lines have
# changed since the last simplifier pass and, once that crosses a threshold,
# blocks the stop and asks Claude to run the code-simplifier subagent over
# exactly the files that changed. Below the threshold it stays silent, so
# ordinary small edits never trigger a pass.
#
#   (no args)     Stop-hook mode: read the hook payload on stdin, decide
#   --checkpoint  reset the baseline to the current tree (after a pass)
#   --status      print the pending churn without deciding anything
#
# Tune with SIMPLIFY_CHURN_THRESHOLD (lines of churn; default 80).

set -uo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
baseline="$root/.claude/.simplify-baseline"
threshold="${SIMPLIFY_CHURN_THRESHOLD:-80}"
sources=(src tests aws)

source_files() {
    (cd -- "$1" 2>/dev/null && find "${sources[@]}" -type f -name '*.py' 2>/dev/null | sed 's|^\./||' | sort)
}

changed_paths() {
    printf '%s\n%s\n' "$(source_files "$root")" "$(source_files "$baseline")" | sort -u | sed '/^$/d'
}

churn_of() {
    local rel="$1" old="$baseline/$1" new="$root/$1" lines
    [ -f "$old" ] || old=/dev/null
    [ -f "$new" ] || new=/dev/null
    lines=$(diff -U0 -- "$old" "$new" | grep -cE '^[-+]')
    [ "$lines" -gt 2 ] && echo $(( lines - 2 )) || echo 0
}

snapshot() {
    rm -rf -- "$baseline"
    while IFS= read -r rel; do
        mkdir -p -- "$baseline/$(dirname -- "$rel")"
        cp -- "$root/$rel" "$baseline/$rel"
    done < <(source_files "$root")
}

measure() {
    total=0
    files=()
    while IFS= read -r rel; do
        local lines
        lines=$(churn_of "$rel")
        if [ "$lines" -gt 0 ]; then
            total=$(( total + lines ))
            [ -f "$root/$rel" ] && files+=("$rel")
        fi
    done < <(changed_paths)
}

case "${1-}" in
    --checkpoint)
        snapshot
        echo "simplify-cadence: baseline reset ($(source_files "$root" | wc -l | tr -d ' ') files)" >&2
        exit 0
        ;;
    --status)
        [ -d "$baseline" ] || { echo "simplify-cadence: no baseline yet"; exit 0; }
        measure
        echo "simplify-cadence: ${total} line(s) of churn across ${#files[@]} file(s), threshold ${threshold}"
        printf '  %s\n' "${files[@]-}"
        exit 0
        ;;
esac

payload=$(cat)
[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = true ] && exit 0

# First run: arm the baseline rather than reporting the whole codebase as churn.
[ -d "$baseline" ] || { snapshot; exit 0; }

measure
[ "$total" -ge "$threshold" ] || exit 0
# Deletions count toward churn but leave nothing to simplify.
[ "${#files[@]}" -gt 0 ] || { snapshot; exit 0; }

# Move the baseline forward now, so an ignored nudge can never re-fire in a loop.
snapshot

jq -nc \
    --arg total "$total" \
    --arg count "${#files[@]}" \
    --arg files "$(printf '%s\n' "${files[@]}" | paste -sd ' ' -)" \
    '{
        decision: "block",
        reason: (
            "Simplifier cadence: \($total) lines across \($count) file(s) have changed since the last pass.\n\n" +
            "Run the code-simplifier subagent (Agent tool, subagent_type \"code-simplifier\") scoped to exactly these files: \($files)\n" +
            "Then run `just check`, then `.claude/hooks/simplify-cadence.sh --checkpoint` to absorb the pass into the baseline.\n\n" +
            "Skip the pass — say so briefly and still run --checkpoint — if the work is mid-refactor, if the tree does not already lint/type/test clean, or if the churn is a mechanical/generated change with nothing to simplify."
        ),
        systemMessage: "Simplifier cadence: \($total) lines changed since the last pass — running code-simplifier."
    }'
