import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Runs a test inside an empty temporary working directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def make_config(workdir):
    def _make(**overrides):
        values = dict(jira_project='TEST', jira_url='https://jira.example.org',
                      github_account='acme', github_repo='widgets', github_token='token',
                      labels_mapping_file=str(workdir / 'labels_mapping.txt'),
                      allowed_labels_file=str(workdir / 'allowed_labels.txt'),
                      mapping_output_file=str(workdir / 'jira-keys-to-github-id.txt'))
        values.update(overrides)
        return Config(**values)
    return _make


@pytest.fixture
def sample_xml():
    return str(FIXTURES / 'sample.xml')


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text='', links=None, headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.links = links or {}
        self.headers = headers or {}
        self.content = text.encode()

    def json(self):
        return self._json


class FakeHttp:
    """Records requests and answers them with handlers registered per (method, url-substring)."""

    def __init__(self):
        self.calls = []
        self._handlers = []

    def on(self, method, url_part, handler):
        self._handlers.append((method, url_part, handler))

    def _dispatch(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for m, part, handler in reversed(self._handlers):
            if m == method and part in url:
                result = handler(url, **kwargs)
                return result if isinstance(result, FakeResponse) else FakeResponse(json_data=result)
        raise AssertionError(f'unexpected request {method} {url}')

    def get(self, url, **kwargs):
        return self._dispatch('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self._dispatch('POST', url, **kwargs)

    def patch(self, url, **kwargs):
        return self._dispatch('PATCH', url, **kwargs)

    def calls_to(self, method, url_part):
        return [c for c in self.calls if c[0] == method and url_part in c[1]]


@pytest.fixture
def fake_http(monkeypatch):
    import requests
    fake = FakeHttp()
    monkeypatch.setattr(requests, 'get', fake.get)
    monkeypatch.setattr(requests, 'post', fake.post)
    monkeypatch.setattr(requests, 'patch', fake.patch)
    monkeypatch.setattr('time.sleep', lambda _: None)
    os.environ.pop('JIRA_MIGRATION_INCLUDE_COMPONENT_IN_LABELS', None)
    return fake
