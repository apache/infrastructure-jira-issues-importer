import re

import pytest

from importer import Importer
from project import Project
from utils import read_xml_files

GH = 'https://github.com/acme/widgets/issues?q='
JIRA = 'https://jira.example.org/browse/'


@pytest.fixture
def project_and_importer(make_config, sample_xml):
    config = make_config()
    project = Project(config)
    for f in read_xml_files(sample_xml):
        for item in f.channel.item:
            project.add_item(item)
    return project, Importer(config, project)


def issue(project, key):
    return next(i for i in project.get_issues() if i['key'] == key)


def test_all_link_types_are_collected(project_and_importer):
    project, _ = project_and_importer

    assert issue(project, 'TEST-1')['links'] == [
        ('blocks', 'TEST-2'), ('relates to', 'TEST-99'), ('is related to', 'TEST-3'), ('depends upon', 'TEST-98')]
    assert issue(project, 'TEST-2')['links'] == [('is blocked by', 'TEST-1')]
    assert issue(project, 'TEST-3')['links'] == [('has subtask', 'TEST-5')]
    assert issue(project, 'TEST-4')['links'] == [('is subtask of', 'TEST-3')]


def test_epic_link_is_plain_text(project_and_importer):
    project, _ = project_and_importer
    assert issue(project, 'TEST-2')['epic-link'] == 'TEST-3'
    assert isinstance(issue(project, 'TEST-2')['epic-link'], str)


def _hrefs(comment):
    return dict((text, href) for href, text in re.findall(r'<a href="([^"]+)">([^<]+)</a>', comment['body']))


def test_links_become_one_comment_pointing_to_github_or_jira(project_and_importer):
    project, importer = project_and_importer
    test1 = issue(project, 'TEST-1')
    importer.convert_relationships_to_comments(test1)

    link_comments = [c for c in test1['comments'] if 'Jira issue links' in c['body']]
    assert len(link_comments) == 1
    body = link_comments[0]['body']
    assert 'blocks <a' in body and 'depends upon <a' in body and 'relates to <a' in body

    hrefs = _hrefs(link_comments[0])
    # migrated issues: search by key in the GitHub title, others: the Jira issue
    assert hrefs['TEST-2'] == GH + 'is%3Aissue%20in%3Atitle%20%22TEST-2%22'
    assert hrefs['TEST-99'] == JIRA + 'TEST-99'
    assert hrefs['TEST-98'] == JIRA + 'TEST-98'
    assert 'links' not in test1


def test_epic_comment_keeps_format_used_by_post_processing(project_and_importer):
    project, importer = project_and_importer
    test2 = issue(project, 'TEST-2')
    importer.convert_relationships_to_comments(test2)

    epic = [c for c in test2['comments'] if c['body'].startswith('<i>[Epic:')]
    assert len(epic) == 1
    # post_process_issues.sh extracts the key from the anchor text
    assert re.match(r'^<i>\[Epic: <a href="[^"]+">TEST-3</a>\]</i>$', epic[0]['body'])
    assert 'epic-link' not in test2


def test_issue_without_links_gets_no_link_comment(project_and_importer, make_config):
    project, importer = project_and_importer
    test3 = dict(issue(project, 'TEST-3'), links=[], comments=[])
    importer.convert_relationships_to_comments(test3)
    assert test3['comments'] == []
