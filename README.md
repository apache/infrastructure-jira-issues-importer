# JIRA issues importer

Python scripts for importing Jira issues (XML search request export) into GitHub issues of an
existing repository, using the GitHub Issue Import API.

Everything project specific lives in configuration (environment variables, label mapping,
comment template), so a migration needs no code changes. See [`examples/opennlp`](examples/opennlp)
for a complete example.

# Features

* Fetch Jira issues for any JQL query (e.g. only open issues) as XML, paginated
* Import Jira fix versions as GitHub milestones (existing milestones are reused by title)
* Import Jira issue types, components and labels as GitHub labels, mapped through a mapping file
  and an optional allow list (existing labels are reused)
* Import Jira issues as GitHub issues where
  * the title keeps the Jira key, e.g. `[PROJECT-123] Summary`
  * the body keeps the Jira description, followed by a collapsible block with reporter, assignee,
    status, priority, resolution, attachments (linked to Jira) and a link to the Jira issue
  * creation, update and close dates and the open/closed state are preserved
  * comments are imported with their original author (as text) and date; comments of selected
    users (e.g. bots) can be skipped
  * all Jira issue links (any link type), subtasks and the parent task are listed in a comment,
    linking to the GitHub issue when it is part of the import, otherwise to Jira
  * epic links are kept as `[Epic: KEY]` comment, `post_process_issues.sh` adds the children to the epic
  * texts longer than GitHub's limit are truncated with a link to the full text in Jira
* Resumable: a `JIRA-KEY:github number` mapping file is written, a rerun skips imported issues
* Comment on the migrated Jira issues with a link to the new GitHub issue (`jira_commenter.py`)

# Caveats

* Jira users are not mapped to GitHub users. The owner of the GitHub token appears as author of all
  issues and comments; the original Jira reporter, assignee and comment authors are noted in the text.
* Attachments cannot be uploaded with the Import API; they are linked to Jira.
* GitHub issue numbers differ from the Jira numbers (the repository may already contain issues and
  pull requests). The Jira key stays in the title, so issues can be found by key.
* Watchers, votes and work logs are not migrated.

# Setup

* install [uv](https://docs.astral.sh/uv/) and run `uv sync`
  * alternatively, without uv: `pip install -r requirements.txt` (generated via
    `uv export --no-dev --no-hashes -o requirements.txt`)
* run the tests with `uv run pytest`
* get a GitHub token with write access to the target repository; treat it like a password
  * classic token with `repo` scope: issues are created with the Issue Import API, which keeps the
    original creation, update and close dates and does not send notifications
  * fine-grained token (Issues: read and write): the Issue Import API rejects these, so the regular
    Issues API is used (issue, comments one by one, then closing). GitHub shows the import date;
    the original dates are written into the issue and comment text. Watchers get notified, and
    GitHub's secondary rate limits (about 80 writes per minute, 500 per hour) make large imports
    slower; the importer waits and retries when it is rate limited

# Configuration

All settings are environment variables; required ones that are missing are asked for interactively.
Put the non-secret ones in an env file and run the scripts with `uv run --env-file <file> <script>`.
Variables already set in the environment take precedence over the env file.

| Variable (`JIRA_MIGRATION_` prefix) | Default | Description |
|---|---|---|
| `JIRA_URL` | (required) | Jira base URL, e.g. `https://issues.apache.org/jira` |
| `JIRA_PROJECT_NAME` | (required) | Jira project key; items of other projects are skipped |
| `JQL_QUERY` | | Query for `fetch_issues.py`, e.g. `project = X AND resolution = Unresolved ORDER BY key ASC` |
| `JIRA_OUTPUT_DIR` | `jira_output` | Where `fetch_issues.py` writes the XML files |
| `JIRA_PAGE_SIZE` | `1000` | Issues per XML file |
| `FILE_PATHS` | | XML files / directories to import (`;` separated) |
| `JIRA_DONE_ID` | `3` | `statusCategory` id meaning "done" (closed on GitHub) |
| `JIRA_TOKEN` / `JIRA_USER` + `JIRA_PASSWORD` | | Jira auth (Bearer PAT or basic), for the commenter and non public projects |
| `GITHUB_NAME` / `GITHUB_REPO` | (required for import) | Target repository owner and name |
| `GITHUB_ACCESS_TOKEN` | (required for import) | GitHub token |
| `GITHUB_IMPORT_API` | `auto` | `import` (Issue Import API, classic token, keeps dates), `rest` (regular Issues API, also fine-grained tokens) or `auto` (`rest` for `github_pat_` tokens) |
| `GITHUB_WRITE_DELAY` | `1.0` | Seconds between write requests in `rest` mode |
| `GITHUB_API_URL` / `GITHUB_URL` | `https://api.github.com` / `https://github.com` | For GitHub Enterprise |
| `LABELS_MAPPING_FILE` | `labels_mapping.txt` | `jira candidate=github label` lines, see below |
| `ALLOWED_LABELS_FILE` | `allowed_labels.txt` | One GitHub label per line; missing file = all labels allowed |
| `INCLUDE_COMPONENT_IN_LABELS` | `true` | Turn components into labels |
| `COMPONENT_LABEL_PREFIX` | `jira-component:` | Prefix for component labels (may be empty) |
| `IMPORTED_LABEL` | `imported-jira-issue` | Label added to every imported issue (empty = none) |
| `SKIP_COMMENT_AUTHORS` | | Comma separated Jira users whose comments are not migrated |
| `MAX_TEXT_LENGTH` | `60000` | Longer descriptions/comments are truncated (GitHub limit: 65536) |
| `MAPPING_OUTPUT_FILE` | `jira-keys-to-github-id.txt` | `JIRA-KEY:number` lines written by the import |
| `JIRA_COMMENT_TEMPLATE_FILE` | built-in text | Comment for `jira_commenter.py`; placeholders `{key}`, `{issue_number}`, `{issue_url}`, `{repo_url}` |
| `START_FROM` | `0` | Skip the first N issues (normally not needed, reruns skip imported issues) |
| `ASSUME_YES` | `false` | Do not wait for confirmation before importing |

## Labels

Every issue type, component and Jira label becomes a lower-cased *candidate* (components get
`COMPONENT_LABEL_PREFIX`). Each candidate is looked up in the mapping file; unmapped candidates are
used as they are, an empty mapping value drops the label. If an allow list exists, only labels on it
are kept. `uv run fetch_labels.py` prints all candidates with counts and the resulting GitHub labels,
which is the easiest way to write the mapping file:

```
# lines starting with # and blank lines are ignored
bug=bug
new feature=enhancement
jira-component:build, packaging and test=component: build
help-wanted=help wanted
gsoc2015=
```

# Running a migration

1. Fetch the issues: `uv run --env-file my.env fetch_issues.py` (or export XML from the Jira UI,
   max 1000 issues per file)
2. Check the labels: `uv run --env-file my.env fetch_labels.py`, adjust the mapping file
3. Dry run against a test repository (with your own token), inspect the result, then clean up with
   `./reset-migration.sh owner/test-repo` (deletes **all** issues and labels of that repository, so
   never use it on a real one) and repeat:

   ```
   JIRA_MIGRATION_GITHUB_NAME=me JIRA_MIGRATION_GITHUB_REPO=import-test uv run --env-file my.env main.py
   ```
4. Import into the real repository: `uv run --env-file my.env main.py`. If it aborts, just run it
   again; issues listed in the mapping output file are skipped. Keep that file.
5. Optionally add epic children to the epics: `./post_process_issues.sh owner repo`
6. Comment on the Jira issues: `uv run --env-file my.env jira_commenter.py --dry-run`, then without
   `--dry-run`

The import:

* imports the milestones with the [GitHub Milestone API](https://docs.github.com/en/rest/issues/milestones)
* imports the labels with the [GitHub Label API](https://docs.github.com/en/rest/issues/labels)
* imports the issues with comments with the [GitHub Issue Import API](https://gist.github.com/jonmagic/5282384165e0f86ef105),
  which does not run into the abuse rate limits of the regular Issues API

# Exporting Jira issues manually

1. Navigate to Issues --> Search for Issues and select the project
2. Specify the query; for more than 1000 issues select ranges such as
   `project = X AND issuekey <= X-3000 AND issuekey > X-2000` and export each into a separate file
3. Click Export at the top right of the results page, select XML and save the file
