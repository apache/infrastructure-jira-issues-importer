import pytest

from conftest import FakeResponse
from config import Config
from importer import Importer
from project import Project
from utils import read_xml_files


@pytest.fixture
def rest_setup(make_config, sample_xml, fake_http):
    def _setup(**overrides):
        config = make_config(github_import_api='rest', **overrides)
        project = Project(config)
        for f in read_xml_files(sample_xml):
            for item in f.channel.item:
                project.add_item(item)
        numbers = iter(range(100, 200))
        fake_http.on('POST', '/issues', lambda url, **kw: FakeResponse(201, {'number': next(numbers)}))
        fake_http.on('POST', '/comments', lambda url, **kw: FakeResponse(201, {}))
        fake_http.on('PATCH', '/issues/', lambda url, **kw: FakeResponse(200, {}))
        importer = Importer(config, project)
        importer.milestone_numbers = {'1.0.0': 5, '2.0.0': 6}
        return config, project, importer
    return _setup


def _created(fake_http):
    return [c for c in fake_http.calls_to('POST', '/issues') if not c[1].endswith('/comments')]


@pytest.mark.parametrize('token, mode, expected', [
    ('github_pat_abc', 'auto', 'rest'), ('ghp_abc', 'auto', 'import'),
    ('github_pat_abc', 'import', 'import'), ('ghp_abc', 'REST', 'rest')])
def test_api_mode_resolution(token, mode, expected):
    config = Config(jira_project='T', jira_url='u', github_token=token, github_import_api=mode)
    assert config.resolved_github_import_api == expected


def test_invalid_api_mode_is_rejected():
    with pytest.raises(ValueError, match='GITHUB_IMPORT_API'):
        Config(jira_project='T', jira_url='u', github_import_api='graphql').resolved_github_import_api


def test_rest_mode_creates_issues_comments_and_closes(rest_setup, fake_http, workdir):
    config, project, importer = rest_setup()
    importer.import_issues(0)

    created = _created(fake_http)
    assert [c[2]['json']['title'][:8] for c in created] == ['[TEST-1]', '[TEST-2]', '[TEST-3]', '[TEST-4]']
    first = created[0][2]['json']
    assert set(first) <= {'title', 'body', 'labels', 'milestone'}
    assert first['milestone'] == 5
    assert '<li><b>created</b>: ' in first['body']
    assert first['body'].endswith('</ul></i>\n</details>')
    assert fake_http.calls_to('POST', '/import/issues') == []

    comments = fake_http.calls_to('POST', '/comments')
    assert comments and all(c[2]['json']['body'] for c in comments)
    assert any(' commented on 20' in c[2]['json']['body'] and ' UTC:</i>\n' in c[2]['json']['body'] for c in comments)

    closes = fake_http.calls_to('PATCH', '/issues/')
    assert [c[1].rsplit('/', 1)[1] for c in closes] == ['103']
    assert closes[0][2]['json'] == {'state': 'closed', 'state_reason': 'completed'}

    mapping = (workdir / 'jira-keys-to-github-id.txt').read_text().splitlines()
    assert mapping == ['TEST-1:100', 'TEST-2:101', 'TEST-3:102', 'TEST-4:103']


def test_rest_mode_retries_after_secondary_rate_limit(rest_setup, fake_http, workdir):
    config, project, importer = rest_setup()
    answers = iter([FakeResponse(403, {}, text='You have exceeded a secondary rate limit',
                                 headers={'retry-after': '5'})])
    numbers = iter(range(100, 200))
    fake_http.on('POST', '/issues', lambda url, **kw: next(answers, None) or FakeResponse(201, {'number': next(numbers)}))
    fake_http.on('POST', '/comments', lambda url, **kw: FakeResponse(201, {}))
    importer.import_issues(0)
    assert (workdir / 'jira-keys-to-github-id.txt').read_text().splitlines()[0] == 'TEST-1:100'


def test_rest_mode_failure_is_reported_without_mapping_entry(rest_setup, fake_http, workdir):
    config, project, importer = rest_setup()
    fake_http.on('POST', '/issues', lambda url, **kw: FakeResponse(403, {}, text='Resource not accessible'))
    with pytest.raises(RuntimeError, match='Failed to create issue'):
        importer.import_issues(0)
    assert not (workdir / 'jira-keys-to-github-id.txt').exists()


def test_comment_date_is_added_to_the_author_header():
    header = '<i><a href="https://jira/ViewProfile.jspa?name=joe">joe</a>:</i>\ntext'
    assert Importer._with_comment_date({'body': header, 'created_at': '2019-06-12T16:50:52+00:00'}) == \
        '<i><a href="https://jira/ViewProfile.jspa?name=joe">joe</a> commented on 2019-06-12 16:50 UTC:</i>\ntext'
    assert Importer._with_comment_date({'body': 'links', 'created_at': '2019-06-12T18:50:52+02:00'}) == \
        '<i>2019-06-12 16:50 UTC</i>\nlinks'
    assert Importer._with_comment_date({'body': 'links'}) == 'links'


def test_auto_mode_falls_back_to_rest_when_import_api_is_refused(make_config, sample_xml, fake_http, workdir):
    config = make_config(github_token='ghp_classic', github_import_api='auto')
    project = Project(config)
    for f in read_xml_files(sample_xml):
        for item in f.channel.item:
            project.add_item(item)
    numbers = iter(range(100, 200))
    fake_http.on('POST', '/issues', lambda url, **kw: FakeResponse(201, {'number': next(numbers)}))
    fake_http.on('POST', '/comments', lambda url, **kw: FakeResponse(201, {}))
    fake_http.on('PATCH', '/issues/', lambda url, **kw: FakeResponse(200, {}))
    # registered last: handlers are matched by URL substring, latest first
    fake_http.on('POST', '/import/issues', lambda url, **kw: FakeResponse(404, {}, text='Not Found'))
    importer = Importer(config, project)
    importer.milestone_numbers = {'1.0.0': 5, '2.0.0': 6}
    assert importer.api_mode == 'import'

    importer.import_issues(0)

    assert importer.api_mode == 'rest'
    assert len(fake_http.calls_to('POST', '/import/issues')) == 1
    assert (workdir / 'jira-keys-to-github-id.txt').read_text().splitlines() == \
        ['TEST-1:100', 'TEST-2:101', 'TEST-3:102', 'TEST-4:103']


@pytest.mark.parametrize('status', [403, 404])
def test_explicit_import_mode_does_not_fall_back(make_config, sample_xml, fake_http, status):
    config = make_config(github_token='ghp_classic', github_import_api='import')
    project = Project(config)
    for f in read_xml_files(sample_xml):
        for item in f.channel.item:
            project.add_item(item)
    fake_http.on('POST', '/import/issues', lambda url, **kw: FakeResponse(status, {}, text='refused'))
    importer = Importer(config, project)
    importer.milestone_numbers = {'1.0.0': 5, '2.0.0': 6}
    with pytest.raises(RuntimeError, match='GITHUB_IMPORT_API=rest'):
        importer.import_issues(0)
    assert all('/import/issues' in c[1] for c in fake_http.calls_to('POST', '/issues'))
