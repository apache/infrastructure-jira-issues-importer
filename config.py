"""
Central configuration for the Jira -> GitHub migration.

Every setting is read from a ``JIRA_MIGRATION_*`` environment variable, so a migration
for a specific project is fully described by an env file (see ``examples/``) and no code
has to be changed. Required settings that are not present in the environment are asked
for interactively.
"""

import os
from dataclasses import dataclass

ENV_PREFIX = 'JIRA_MIGRATION_'


def _as_list(value):
    return tuple(part.strip() for part in str(value).split(',') if part.strip())


def _as_bool(value):
    return str(value).strip().lower() in ('1', 'true', 'yes', 'y', 'on')


@dataclass(frozen=True)
class Config:
    # Jira
    jira_project: str
    jira_url: str
    jira_done_id: str = '3'
    file_paths: str = ''
    jql_query: str = ''
    jira_output_dir: str = 'jira_output'
    jira_page_size: int = 1000
    jira_token: str = ''
    jira_user: str = ''
    jira_password: str = ''

    # GitHub
    github_account: str = ''
    github_repo: str = ''
    github_token: str = ''
    github_api_url: str = 'https://api.github.com'
    github_url: str = 'https://github.com'
    # 'import': Issue Import API (classic tokens only, keeps dates);
    # 'rest': regular Issues API (works with fine-grained tokens, dates noted in the text);
    # 'auto': 'rest' for fine-grained tokens (github_pat_...), otherwise 'import'
    github_import_api: str = 'auto'
    # pause between write requests of the 'rest' mode, to stay below GitHub's secondary rate limits
    github_write_delay: float = 1.0

    # Labels
    labels_mapping_file: str = 'labels_mapping.txt'
    allowed_labels_file: str = 'allowed_labels.txt'
    include_component_in_labels: bool = True
    component_label_prefix: str = 'jira-component:'
    imported_label: str = 'imported-jira-issue'

    # Comments by these Jira users are not migrated (e.g. bots mirroring GitHub PR activity)
    skip_comment_authors: tuple = ()

    # GitHub rejects bodies/comments over 65536 characters; longer texts are truncated
    # (with a link to the full text in Jira). Kept below the limit as a safety margin.
    max_text_length: int = 60000

    # Jira commenter: template with {key}, {issue_url}, {repo_url}, {issue_number} placeholders
    jira_comment_template_file: str = ''

    # Run control
    start_from: int = 0
    mapping_output_file: str = 'jira-keys-to-github-id.txt'
    assume_yes: bool = False

    @property
    def resolved_github_import_api(self):
        mode = self.github_import_api.strip().lower()
        if mode == 'auto':
            return 'rest' if self.github_token.startswith('github_pat_') else 'import'
        if mode not in ('import', 'rest'):
            raise ValueError(f"JIRA_MIGRATION_GITHUB_IMPORT_API must be auto, import or rest, not '{mode}'")
        return mode

    @property
    def jira_url_normalized(self):
        return self.jira_url.rstrip('/')

    @property
    def github_repo_url(self):
        return f'{self.github_url.rstrip("/")}/{self.github_account}/{self.github_repo}'

    @property
    def github_repo_api_url(self):
        return f'{self.github_api_url.rstrip("/")}/repos/{self.github_account}/{self.github_repo}'


# setting name -> (env suffix, converter)
_FIELDS = {
    'jira_project': ('JIRA_PROJECT_NAME', str),
    'jira_url': ('JIRA_URL', str),
    'jira_done_id': ('JIRA_DONE_ID', str),
    'file_paths': ('FILE_PATHS', str),
    'jql_query': ('JQL_QUERY', str),
    'jira_output_dir': ('JIRA_OUTPUT_DIR', str),
    'jira_page_size': ('JIRA_PAGE_SIZE', int),
    'jira_token': ('JIRA_TOKEN', str),
    'jira_user': ('JIRA_USER', str),
    'jira_password': ('JIRA_PASSWORD', str),
    'github_account': ('GITHUB_NAME', str),
    'github_repo': ('GITHUB_REPO', str),
    'github_token': ('GITHUB_ACCESS_TOKEN', str),
    'github_api_url': ('GITHUB_API_URL', str),
    'github_url': ('GITHUB_URL', str),
    'github_import_api': ('GITHUB_IMPORT_API', str),
    'github_write_delay': ('GITHUB_WRITE_DELAY', float),
    'labels_mapping_file': ('LABELS_MAPPING_FILE', str),
    'allowed_labels_file': ('ALLOWED_LABELS_FILE', str),
    'include_component_in_labels': ('INCLUDE_COMPONENT_IN_LABELS', _as_bool),
    'component_label_prefix': ('COMPONENT_LABEL_PREFIX', str),
    'imported_label': ('IMPORTED_LABEL', str),
    'skip_comment_authors': ('SKIP_COMMENT_AUTHORS', _as_list),
    'max_text_length': ('MAX_TEXT_LENGTH', int),
    'jira_comment_template_file': ('JIRA_COMMENT_TEMPLATE_FILE', str),
    'start_from': ('START_FROM', int),
    'mapping_output_file': ('MAPPING_OUTPUT_FILE', str),
    'assume_yes': ('ASSUME_YES', _as_bool),
}

_PROMPTS = {
    'file_paths': 'Path to Jira XML query file (semi-colon separate for multiple files, directories are accepted): ',
    'jira_project': 'Jira project key (e.g. OPENNLP): ',
    'jira_url': 'Jira base url (e.g. https://issues.apache.org/jira): ',
    'jql_query': 'JQL query: ',
    'github_account': 'GitHub account name (user/org): ',
    'github_repo': 'GitHub repository name: ',
    'github_token': 'GitHub access token: ',
}


def env_name(field):
    return ENV_PREFIX + _FIELDS[field][0]


def load_config(required=(), env=None, ask=input):
    """
    Builds a Config from the environment. Settings listed in ``required`` that are not set
    in the environment are asked for via ``ask``; a missing answer raises ValueError.
    Empty environment values are treated as "not set", except for settings that may
    legitimately be empty (e.g. COMPONENT_LABEL_PREFIX), which use ``is not None``.
    """
    env = os.environ if env is None else env
    values = {}
    for field, (suffix, convert) in _FIELDS.items():
        raw = env.get(ENV_PREFIX + suffix)
        if raw is None or (raw == '' and field != 'component_label_prefix' and field != 'imported_label'):
            continue
        values[field] = convert(raw)

    for field in ('jira_project', 'jira_url', *required):
        if values.get(field) in (None, ''):
            answer = ask(_PROMPTS.get(field, f'{env_name(field)}: ')).strip()
            if not answer:
                raise ValueError(f'Missing required setting {env_name(field)}')
            values[field] = _FIELDS[field][1](answer)

    return Config(**values)
