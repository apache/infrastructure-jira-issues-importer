#!/usr/bin/env bash
# Adds the children of each imported epic to the epic's description ("Epic children:" list).
# Epic membership is taken from the "[Epic: <a ...>KEY</a>]" comment written by the importer.
#
# Usage: ./post_process_issues.sh <owner> <repo> [start from issue number] [imported label]

set -euo pipefail

OWNER=${1:?usage: $0 <owner> <repo> [start from issue number] [imported label]}
REPO=${2:?usage: $0 <owner> <repo> [start from issue number] [imported label]}
START_FROM=${3:-0}
LABEL=${4:-imported-jira-issue}

ALL_ISSUE_NUMBERS=$(gh issue list -R "${OWNER}/${REPO}" --limit=20000 --state=all --label "${LABEL}" --json number \
  | jq '.[].number' | sort -g | uniq)

while IFS= read -r ISSUE_CHECKING; do
  if [[ -z "${ISSUE_CHECKING}" ]] || (( ISSUE_CHECKING < START_FROM )); then
    continue
  fi
  echo "Checking ${ISSUE_CHECKING}"
  COMMENT=$(gh issue view -R "${OWNER}/${REPO}" "${ISSUE_CHECKING}" --comments --json 'comments' \
    --jq '.comments[].body | select(contains("[Epic:"))')

  if [[ -n "${COMMENT}" ]]; then
    JIRA_ISSUE_KEY=$(echo "${COMMENT}" | sed -E 's#^.*<a href="[^"]+">([^<]+)</a>.*$#\1#')
    echo "Found epic ${JIRA_ISSUE_KEY}"

    EPIC_ISSUE_NUMBER=$(gh search issues --owner "${OWNER}" --repo "${OWNER}/${REPO}" --match title "${JIRA_ISSUE_KEY}" \
      --json number,repository \
      | jq ".[] | select(.repository.nameWithOwner == \"${OWNER}/${REPO}\").number")

    # can be empty if the epic was not imported (e.g. it is closed and stays in Jira)
    if [[ -n "${EPIC_ISSUE_NUMBER}" ]]; then
      echo "Found issue for epic: ${EPIC_ISSUE_NUMBER}"
      BODY=$(gh issue view -R "${OWNER}/${REPO}" "${EPIC_ISSUE_NUMBER}" --json body --jq '.body')

      if [[ "${BODY}" == *"Epic children:"* ]]; then
        BODY+=$'\n'"- #${ISSUE_CHECKING}"
      else
        BODY+=$'\n\nEpic children:\n\n'"- #${ISSUE_CHECKING}"
      fi
      gh issue edit -R "${OWNER}/${REPO}" "${EPIC_ISSUE_NUMBER}" --body "${BODY}"
    fi
  fi
done <<< "${ALL_ISSUE_NUMBERS}"
