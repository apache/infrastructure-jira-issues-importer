import pytest

from conftest import FakeResponse


@pytest.fixture
def mapping(workdir):
    path = workdir / 'jira-keys-to-github-id.txt'
    path.write_text('TEST-1:100\nTEST-2:101\n\n')
    return path


def test_comments_each_migrated_issue(make_config, fake_http, mapping):
    import jira_commenter
    config = make_config(jira_token='pat')
    fake_http.on('POST', '/rest/api/2/issue/', lambda url, **kw: FakeResponse(201, {}))

    done = jira_commenter.comment_all(config)

    assert done == ['TEST-1', 'TEST-2']
    calls = fake_http.calls_to('POST', '/rest/api/2/issue/')
    assert [c[1] for c in calls] == ['https://jira.example.org/rest/api/2/issue/TEST-1/comment',
                                     'https://jira.example.org/rest/api/2/issue/TEST-2/comment']
    assert calls[0][2]['headers']['Authorization'] == 'Bearer pat'
    body = calls[0][2]['json']['body']
    assert 'https://github.com/acme/widgets/issues/100' in body


def test_custom_template(make_config, fake_http, mapping, workdir):
    import jira_commenter
    (workdir / 'template.txt').write_text('Moved to {issue_url} ("{key}") in {repo_url}')
    config = make_config(jira_token='pat', jira_comment_template_file=str(workdir / 'template.txt'))
    fake_http.on('POST', '/rest/api/2/issue/', lambda url, **kw: FakeResponse(201, {}))

    jira_commenter.comment_all(config)

    body = fake_http.calls_to('POST', '/rest/api/2/issue/')[1][2]['json']['body']
    assert body == 'Moved to https://github.com/acme/widgets/issues/101 ("TEST-2") in https://github.com/acme/widgets'


def test_dry_run_sends_nothing(make_config, fake_http, mapping, capsys):
    import jira_commenter
    jira_commenter.comment_all(make_config(), dry_run=True)

    assert fake_http.calls == []
    assert 'TEST-2' in capsys.readouterr().out


def test_already_commented_issues_are_skipped_on_rerun(make_config, fake_http, mapping, workdir):
    import jira_commenter
    config = make_config(jira_token='pat')
    (workdir / 'jira-keys-to-github-id.txt.commented').write_text('TEST-1\n')
    fake_http.on('POST', '/rest/api/2/issue/', lambda url, **kw: FakeResponse(201, {}))

    assert jira_commenter.comment_all(config) == ['TEST-2']
    assert (workdir / 'jira-keys-to-github-id.txt.commented').read_text().split() == ['TEST-1', 'TEST-2']


def test_failure_stops_with_error(make_config, fake_http, mapping):
    import jira_commenter
    fake_http.on('POST', '/rest/api/2/issue/', lambda url, **kw: FakeResponse(403, {}, text='forbidden'))
    with pytest.raises(RuntimeError, match='TEST-1.*403'):
        jira_commenter.comment_all(make_config(jira_token='pat'))


def test_template_may_contain_jira_wiki_braces(make_config, fake_http, mapping, workdir):
    import jira_commenter
    (workdir / 'template.txt').write_text('{quote}Moved to {issue_url}{quote}')
    config = make_config(jira_token='pat', jira_comment_template_file=str(workdir / 'template.txt'))
    fake_http.on('POST', '/rest/api/2/issue/', lambda url, **kw: FakeResponse(201, {}))

    jira_commenter.comment_all(config)

    body = fake_http.calls_to('POST', '/rest/api/2/issue/')[0][2]['json']['body']
    assert body == '{quote}Moved to https://github.com/acme/widgets/issues/100{quote}'


def test_closes_with_comment_in_one_transition(make_config, fake_http, mapping):
    import jira_commenter
    config = make_config(jira_token='pat', jira_close_transition='close issue',
                         jira_close_resolution='Auto Closed')
    transitions = {'transitions': [{'id': '5', 'name': 'Resolve Issue', 'fields': {'resolution': {}}},
                                   {'id': '2', 'name': 'Close Issue', 'fields': {'resolution': {}}}]}
    fake_http.on('GET', '/transitions', lambda url, **kw: FakeResponse(200, transitions))
    fake_http.on('POST', '/transitions', lambda url, **kw: FakeResponse(204, None))

    assert jira_commenter.comment_all(config) == ['TEST-1', 'TEST-2']

    posts = fake_http.calls_to('POST', '/rest/api/2/issue/')
    assert [c[1] for c in posts] == ['https://jira.example.org/rest/api/2/issue/TEST-1/transitions',
                                     'https://jira.example.org/rest/api/2/issue/TEST-2/transitions']
    data = posts[0][2]['json']
    assert data['transition'] == {'id': '2'}
    assert data['fields'] == {'resolution': {'name': 'Auto Closed'}}
    assert 'https://github.com/acme/widgets/issues/100' in data['update']['comment'][0]['add']['body']


def test_already_closed_issue_only_gets_the_comment(make_config, fake_http, mapping):
    import jira_commenter
    config = make_config(jira_token='pat', jira_close_transition='Close Issue')
    fake_http.on('GET', '/transitions', lambda url, **kw: FakeResponse(200, {'transitions': [{'id': '3', 'name': 'Reopen Issue'}]}))
    fake_http.on('POST', '/comment', lambda url, **kw: FakeResponse(201, {}))

    assert jira_commenter.comment_all(config) == ['TEST-1', 'TEST-2']
    assert fake_http.calls_to('POST', '/transitions') == []
    assert len(fake_http.calls_to('POST', '/comment')) == 2


def test_close_failure_stops_without_marking_done(make_config, fake_http, mapping, workdir):
    import jira_commenter
    config = make_config(jira_token='pat', jira_close_transition='Close Issue')
    fake_http.on('GET', '/transitions', lambda url, **kw: FakeResponse(200, {'transitions': [{'id': '2', 'name': 'Close Issue'}]}))
    fake_http.on('POST', '/transitions', lambda url, **kw: FakeResponse(400, {}, text='bad resolution'))

    with pytest.raises(RuntimeError, match='Closing TEST-1 failed'):
        jira_commenter.comment_all(config)
    assert not (workdir / 'jira-keys-to-github-id.txt.commented').exists()
