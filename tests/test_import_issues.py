import pytest

from conftest import FakeResponse
from importer import Importer
from project import Project
from utils import read_xml_files

ALLOWED_ISSUE_FIELDS = {'title', 'body', 'created_at', 'updated_at', 'closed', 'closed_at', 'labels',
                        'milestone', 'assignee'}


@pytest.fixture
def setup(make_config, sample_xml, fake_http):
    def _setup(**overrides):
        config = make_config(**overrides)
        project = Project(config)
        for f in read_xml_files(sample_xml):
            for item in f.channel.item:
                project.add_item(item)

        numbers = iter(range(100, 200))
        statuses = {}

        def upload(url, json, **kwargs):
            number = next(numbers)
            statuses[number] = json
            return FakeResponse(202, {'url': f'https://api.github.com/status/{number}'})

        def status(url, **kwargs):
            number = int(url.rsplit('/', 1)[1])
            return FakeResponse(200, {'status': 'imported',
                                      'issue_url': f'https://api.github.com/repos/acme/widgets/issues/{number}'})

        fake_http.on('POST', '/import/issues', upload)
        fake_http.on('GET', '/status/', status)
        importer = Importer(config, project)
        importer.milestone_numbers = {'1.0.0': 5, '2.0.0': 6}
        return config, project, importer
    return _setup


def _uploads(fake_http):
    return [c[2]['json'] for c in fake_http.calls_to('POST', '/import/issues')]


def test_issues_are_uploaded_with_clean_payload_and_mapping_is_written(setup, fake_http, workdir):
    config, project, importer = setup()
    importer.import_issues(0)

    uploads = _uploads(fake_http)
    assert [u['issue']['title'] for u in uploads] == ['[TEST-1] Tokenizer drops trailing dots',
                                                     '[TEST-2] Improve sentence detector',
                                                     '[TEST-3] Modernize pipeline', '[TEST-4] Old wish']
    for upload in uploads:
        assert set(upload['issue']) <= ALLOWED_ISSUE_FIELDS
        for comment in upload['comments']:
            assert set(comment) <= {'body', 'created_at'}

    assert uploads[0]['issue']['milestone'] == 5
    assert uploads[2]['issue']['milestone'] == 6
    assert 'milestone' not in uploads[1]['issue']
    assert uploads[3]['issue']['closed'] is True
    assert uploads[3]['issue']['closed_at'] == '2025-11-08T10:00:00+00:00'

    mapping = (workdir / 'jira-keys-to-github-id.txt').read_text().splitlines()
    assert mapping == ['TEST-1:100', 'TEST-2:101', 'TEST-3:102', 'TEST-4:103']


def test_rerun_skips_issues_already_imported(setup, fake_http, workdir):
    (workdir / 'jira-keys-to-github-id.txt').write_text('TEST-1:42\nTEST-2:43\n')
    config, project, importer = setup()

    importer.import_issues(0)

    assert [u['issue']['title'][:8] for u in _uploads(fake_http)] == ['[TEST-3]', '[TEST-4]']
    assert (workdir / 'jira-keys-to-github-id.txt').read_text().splitlines()[-2:] == ['TEST-3:100', 'TEST-4:101']


def test_start_from_index_is_still_supported(setup, fake_http):
    config, project, importer = setup()
    importer.import_issues(3)
    assert [u['issue']['title'][:8] for u in _uploads(fake_http)] == ['[TEST-4]']


def test_unresolved_milestone_fails_instead_of_sending_a_count(make_config, sample_xml, fake_http):
    config = make_config()
    project = Project(config)
    for f in read_xml_files(sample_xml):
        for item in f.channel.item:
            project.add_item(item)
    # import_milestones() not run: values are still usage counts, not milestone numbers
    with pytest.raises(RuntimeError, match='milestone'):
        Importer(config, project).import_issues(0)
    assert _uploads(fake_http) == []


def test_failed_import_status_raises(setup, fake_http):
    config, project, importer = setup()
    fake_http.on('GET', '/status/', lambda url, **kw: FakeResponse(200, {'status': 'failed', 'errors': ['boom']}))
    with pytest.raises(RuntimeError, match='boom'):
        importer.import_issues(0)


def test_status_polling_gives_up(setup, fake_http):
    config, project, importer = setup()
    fake_http.on('GET', '/status/', lambda url, **kw: FakeResponse(404, {}))
    with pytest.raises(RuntimeError, match='did not finish'):
        importer.import_issues(0)
