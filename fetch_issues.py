#!/usr/bin/env python3
"""
Downloads the Jira issues matching JIRA_MIGRATION_JQL_QUERY as XML search request exports
(one file per page) into JIRA_MIGRATION_JIRA_OUTPUT_DIR (default: jira_output).

Example (only open issues):
  JIRA_MIGRATION_JQL_QUERY='project = OPENNLP AND resolution = Unresolved ORDER BY key ASC'
"""

import os
from urllib.parse import quote

import requests
from lxml import etree, objectify

from config import load_config

_TIME_OUT = 120.0


def _headers(config):
    if config.jira_token:
        return {'Authorization': f'Bearer {config.jira_token}'}
    return {}


def _fetch_page(config, start, size):
    url = (f'{config.jira_url_normalized}/sr/jira.issueviews:searchrequest-xml/temp/SearchRequest.xml'
           f'?jqlQuery={quote(config.jql_query)}&tempMax={size}&pager/start={start}')
    auth = (config.jira_user, config.jira_password) if config.jira_user and not config.jira_token else None
    response = requests.get(url, headers=_headers(config), auth=auth, timeout=_TIME_OUT)
    if response.status_code != 200:
        raise RuntimeError(f'Jira returned {response.status_code} for {url}:\n{response.text[:1000]}')
    return objectify.fromstring(response.text.encode('utf-8'))


def fetch(config):
    """Fetches all pages and returns the written file paths."""
    os.makedirs(config.jira_output_dir, exist_ok=True)

    total = int(_fetch_page(config, 0, 1).channel.issue.get('total'))
    print(f'{total} issues match: {config.jql_query}')

    files = []
    for start in range(0, total, config.jira_page_size):
        print(f'Fetching issues {start + 1}-{min(start + config.jira_page_size, total)} of {total}')
        root = _fetch_page(config, start, config.jira_page_size)
        path = os.path.join(config.jira_output_dir, f'result-{start}.xml')
        with open(path, 'wb') as doc:
            doc.write(etree.tostring(root, pretty_print=True))
        files.append(path)
    print('Complete')
    return files


if __name__ == '__main__':
    fetch(load_config(required=('jql_query',)))
