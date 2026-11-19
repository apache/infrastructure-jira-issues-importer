import os
import subprocess

import pytest

from conftest import ROOT

FAKE_GH = '''#!/usr/bin/env bash
echo "gh $*" >> "$GH_LOG"
case "$*" in
  "issue list"*) echo '[{"number": 7}, {"number": 8}]' ;;
  "label list"*) echo '[{"name": "bug"}]' ;;
  *"--comments"*) if [[ "$*" == *" 8 "* ]]; then echo '<i>[Epic: <a href="https://x">TEST-3</a>]</i>'; fi ;;
  "search issues"*) echo '[{"number": 7, "repository": {"nameWithOwner": "acme/widgets"}}]' ;;
  *"--json body"*) echo 'Epic body' ;;
esac
'''


@pytest.fixture
def run(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'gh').write_text(FAKE_GH)
    (bin_dir / 'gh').chmod(0o755)
    log = tmp_path / 'gh.log'
    log.touch()

    def _run(script, *args, stdin=''):
        env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', GH_LOG=str(log))
        result = subprocess.run(['bash', str(ROOT / script), *args], input=stdin, env=env,
                                capture_output=True, text=True, timeout=30)
        return result, log.read_text()
    return _run


def test_reset_requires_repo_and_confirmation(run):
    result, log = run('reset-migration.sh')
    assert result.returncode != 0
    assert log == ''

    result, log = run('reset-migration.sh', 'acme/widgets', stdin='no\n')
    assert result.returncode != 0
    assert 'delete' not in log


def test_reset_deletes_after_typing_repo_name(run):
    result, log = run('reset-migration.sh', 'acme/widgets', stdin='acme/widgets\n')
    assert result.returncode == 0, result.stderr
    assert 'issue -R acme/widgets delete 7' in log
    assert 'label delete --yes -R acme/widgets bug' in log


def test_post_process_requires_owner_and_repo(run):
    result, log = run('post_process_issues.sh')
    assert result.returncode != 0
    assert log == ''


def test_post_process_adds_child_to_epic_only_for_imported_issues(run):
    result, log = run('post_process_issues.sh', 'acme', 'widgets')
    assert result.returncode == 0, result.stderr
    assert 'issue list -R acme/widgets --limit=20000 --state=all --label imported-jira-issue' in log
    assert 'issue edit -R acme/widgets 7 --body Epic body\n\nEpic children:\n\n- #8' in log
