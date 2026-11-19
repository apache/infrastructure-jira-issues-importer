import pytest

from config import load_config, Config


def _no_prompt(prompt):
    raise AssertionError(f'unexpected prompt: {prompt}')


def test_reads_all_settings_from_env():
    env = {
        'JIRA_MIGRATION_JIRA_PROJECT_NAME': 'OPENNLP',
        'JIRA_MIGRATION_JIRA_URL': 'https://issues.apache.org/jira/',
        'JIRA_MIGRATION_GITHUB_NAME': 'apache',
        'JIRA_MIGRATION_GITHUB_REPO': 'opennlp',
        'JIRA_MIGRATION_GITHUB_ACCESS_TOKEN': 'secret',
        'JIRA_MIGRATION_INCLUDE_COMPONENT_IN_LABELS': 'false',
        'JIRA_MIGRATION_COMPONENT_LABEL_PREFIX': 'component: ',
        'JIRA_MIGRATION_START_FROM': '7',
    }
    config = load_config(required=('github_token',), env=env, ask=_no_prompt)

    assert config.jira_project == 'OPENNLP'
    assert config.jira_url_normalized == 'https://issues.apache.org/jira'
    assert config.github_repo_api_url == 'https://api.github.com/repos/apache/opennlp'
    assert config.github_repo_url == 'https://github.com/apache/opennlp'
    assert config.include_component_in_labels is False
    assert config.component_label_prefix == 'component: '
    assert config.start_from == 7
    assert config.jira_done_id == '3'


def test_no_project_specific_defaults():
    """Nothing Jenkins (or any other project) specific may leak in as a default."""
    answers = iter(['MYPROJ', 'https://jira.example.org'])
    config = load_config(env={}, ask=lambda _: next(answers))

    assert config.jira_project == 'MYPROJ'
    assert config.jira_url == 'https://jira.example.org'
    assert config.github_account == ''
    assert config.github_repo == ''


def test_missing_required_setting_fails():
    with pytest.raises(ValueError, match='JIRA_MIGRATION_GITHUB_REPO'):
        load_config(required=('github_repo',),
                    env={'JIRA_MIGRATION_JIRA_PROJECT_NAME': 'X', 'JIRA_MIGRATION_JIRA_URL': 'http://j'},
                    ask=lambda _: '')


def test_empty_component_prefix_is_allowed():
    config = load_config(env={'JIRA_MIGRATION_JIRA_PROJECT_NAME': 'X', 'JIRA_MIGRATION_JIRA_URL': 'http://j',
                              'JIRA_MIGRATION_COMPONENT_LABEL_PREFIX': ''}, ask=_no_prompt)
    assert config.component_label_prefix == ''


def test_config_is_immutable():
    config = Config(jira_project='X', jira_url='http://j')
    with pytest.raises(Exception):
        config.jira_project = 'Y'
