import pytest

from conftest import FakeResponse
from importer import Importer
from labelcolourselector import LabelColourSelector
from project import Project
from utils import read_xml_files

MAPPING = '''\
bug=bug
improvement=improvement
wish=improvement
epic=epic
jira-component:tokenizer=component: tokenizer
jira-component:build, packaging and test=component: build
help-wanted=help wanted
gsoc=
'''


@pytest.fixture
def labels_of(make_config, sample_xml, workdir):
    def _labels(mapping=MAPPING, allowed=None, **overrides):
        (workdir / 'labels_mapping.txt').write_text(mapping)
        if allowed is not None:
            (workdir / 'allowed_labels.txt').write_text(allowed)
        project = Project(make_config(**overrides))
        for f in read_xml_files(sample_xml):
            for item in f.channel.item:
                project.add_item(item)
        return project, {i['key']: set(i['labels']) for i in project.get_issues()}
    return _labels


def test_type_component_and_jira_labels_are_mapped(labels_of):
    _, labels = labels_of()

    assert labels['TEST-1'] == {'bug', 'component: tokenizer', 'component: build', 'help wanted',
                                'imported-jira-issue'}
    # type label is added even if the issue has no Jira labels; no fake "miscellaneous" component
    assert labels['TEST-2'] == {'improvement', 'imported-jira-issue'}
    # unmapped component keeps its prefixed name
    assert labels['TEST-3'] == {'epic', 'jira-component:parser', 'imported-jira-issue'}
    assert labels['TEST-4'] == {'improvement', 'imported-jira-issue'}


def test_allow_list_restricts_labels_but_not_the_imported_marker(labels_of):
    _, labels = labels_of(allowed='bug\nepic\ncomponent: build\n')

    assert labels['TEST-1'] == {'bug', 'component: build', 'imported-jira-issue'}
    assert labels['TEST-3'] == {'epic', 'imported-jira-issue'}


def test_components_can_be_excluded(labels_of):
    _, labels = labels_of(include_component_in_labels=False)
    assert labels['TEST-1'] == {'bug', 'help wanted', 'imported-jira-issue'}


def test_component_prefix_is_configurable(labels_of):
    _, labels = labels_of(mapping='', component_label_prefix='component: ')
    assert labels['TEST-3'] == {'epic', 'component: parser', 'imported-jira-issue'}


def test_imported_marker_label_can_be_disabled(labels_of):
    _, labels = labels_of(imported_label='')
    assert labels['TEST-2'] == {'improvement'}


def test_project_label_set_contains_exactly_the_final_labels(labels_of):
    project, labels = labels_of()
    assert set(project.get_all_labels()) == set().union(*labels.values())


def test_label_import_creates_final_labels_and_tolerates_existing(labels_of, fake_http):
    project, _ = labels_of()

    def create(url, json, **kwargs):
        if json['name'] == 'bug':
            return FakeResponse(422, {'errors': [{'code': 'already_exists'}]})
        return FakeResponse(201, {'name': json['name']})

    fake_http.on('POST', '/labels', create)
    Importer(project.config, project).import_labels(LabelColourSelector(project))

    posted = sorted(c[2]['json']['name'] for c in fake_http.calls_to('POST', '/labels'))
    assert posted == sorted(project.get_all_labels())
    assert None not in posted
    colours = {c[2]['json']['name']: c[2]['json']['color'] for c in fake_http.calls_to('POST', '/labels')}
    assert colours['epic'] == 'ddf4dd'
    assert colours['improvement'] == '7bc043'


def test_fetch_labels_prints_mapping_keys(sample_xml, workdir, monkeypatch, capsys):
    import fetch_labels
    for name, value in {'FILE_PATHS': sample_xml, 'JIRA_PROJECT_NAME': 'TEST',
                        'JIRA_URL': 'https://jira.example.org'}.items():
        monkeypatch.setenv('JIRA_MIGRATION_' + name, value)

    fetch_labels.main()
    out = capsys.readouterr().out

    assert 'bug  (1)' in out
    assert 'jira-component:build, packaging and test  (1)' in out
    assert 'help-wanted  (1)' in out
    assert 'imported-jira-issue  (4)' in out
