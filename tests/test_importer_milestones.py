from conftest import FakeResponse
from importer import Importer
from project import Project
from utils import read_xml_files


def _project(config, sample_xml):
    project = Project(config)
    for f in read_xml_files(sample_xml):
        for item in f.channel.item:
            project.add_item(item)
    return project


def test_existing_milestones_are_reused_across_pages_and_missing_ones_created(make_config, sample_xml, fake_http):
    config = make_config()
    project = _project(config, sample_xml)
    base = config.github_repo_api_url + '/milestones'

    def list_milestones(url, **kwargs):
        if 'page=2' in url:
            return FakeResponse(json_data=[{'title': '1.0.0', 'number': 12}])
        return FakeResponse(json_data=[{'title': '0.1.0', 'number': 1}],
                            links={'next': {'url': base + '?state=all&page=2'}})

    fake_http.on('GET', '/milestones', list_milestones)
    fake_http.on('POST', '/milestones', lambda url, json, **kw: FakeResponse(201, {'number': 40, 'title': json['title']}))

    importer = Importer(config, project)
    importer.import_milestones()

    created = [c[2]['json']['title'] for c in fake_http.calls_to('POST', '/milestones')]
    assert created == ['2.0.0']
    assert importer.milestone_numbers == {'1.0.0': 12, '2.0.0': 40}
    # the project keeps the usage counts
    assert dict(project.get_milestones()) == {'1.0.0': 1, '2.0.0': 1}


def test_failed_milestone_creation_raises(make_config, sample_xml, fake_http):
    import pytest
    config = make_config()
    project = _project(config, sample_xml)
    fake_http.on('GET', '/milestones', lambda url, **kw: FakeResponse(json_data=[]))
    fake_http.on('POST', '/milestones', lambda url, **kw: FakeResponse(403, {'message': 'nope'}))

    with pytest.raises(RuntimeError, match='1.0.0'):
        Importer(config, project).import_milestones()
