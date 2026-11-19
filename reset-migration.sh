#!/usr/bin/env bash
# Deletes ALL issues and ALL labels of a (test) repository, to repeat a dry-run import.
#
# CAUTION: never run this against a real project repository. Anything you want to keep
# (e.g. labels used by pull requests) must be managed in code.
#
# Usage: ./reset-migration.sh <owner/repo>

set -euo pipefail

REPO=${1:?usage: $0 <owner/repo>}

echo "This deletes ALL issues and ALL labels of ${REPO}."
read -r -p "Type the repository name (${REPO}) to confirm: " CONFIRM
if [[ "${CONFIRM}" != "${REPO}" ]]; then
  echo "Aborted." >&2
  exit 1
fi

gh issue list -R "${REPO}" -L 20000 -s all --json number | jq -r '.[].number' \
  | xargs -P 10 -I {} gh issue -R "${REPO}" delete {} --yes
gh label list -R "${REPO}" --limit 1000 --json name | jq -r '.[].name' \
  | xargs -P 10 -I {} gh label delete --yes -R "${REPO}" '{}'
