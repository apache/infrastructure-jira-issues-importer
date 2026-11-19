from urllib.parse import urlparse, parse_qs

import pytest

from conftest import FakeResponse

PAGE = '<rss version="0.92"><channel><issue start="{start}" end="{end}" total="{total}"/>{items}</channel></rss>'


def _answer(total):
    def handler(url, **kwargs):
        query = parse_qs(urlparse(url).query)
        start, size = int(query['pager/start'][0]), int(query['tempMax'][0])
        end = min(start + size, total)
        items = ''.join(f'<item><key>TEST-{n}</key></item>' for n in range(start, end))
        return FakeResponse(200, text=PAGE.format(start=start, end=end, total=total, items=items))
    return handler


def test_fetches_all_pages_into_output_dir(make_config, fake_http, workdir):
    import fetch_issues
    config = make_config(jql_query='project = TEST AND resolution = Unresolved', jira_page_size=2,
                         jira_output_dir=str(workdir / 'out'))
    fake_http.on('GET', 'SearchRequest.xml', _answer(5))

    files = fetch_issues.fetch(config)

    assert [f.split('/')[-1] for f in files] == ['result-0.xml', 'result-2.xml', 'result-4.xml']
    assert '<key>TEST-4</key>' in (workdir / 'out' / 'result-4.xml').read_text()
    urls = [c[1] for c in fake_http.calls]
    assert all(u.startswith('https://jira.example.org/sr/jira.issueviews:searchrequest-xml/temp/SearchRequest.xml?') for u in urls)
    assert parse_qs(urlparse(urls[0]).query)['jqlQuery'] == ['project = TEST AND resolution = Unresolved']


def test_bearer_token_is_sent_when_configured(make_config, fake_http, workdir):
    import fetch_issues
    config = make_config(jql_query='project = TEST', jira_token='pat', jira_output_dir=str(workdir / 'o'))
    fake_http.on('GET', 'SearchRequest.xml', _answer(1))

    fetch_issues.fetch(config)

    assert all(c[2]['headers']['Authorization'] == 'Bearer pat' for c in fake_http.calls)


def test_http_error_is_reported(make_config, fake_http, workdir):
    import fetch_issues
    config = make_config(jql_query='project = TEST AND bad', jira_output_dir=str(workdir / 'o'))
    fake_http.on('GET', 'SearchRequest.xml', lambda url, **kw: FakeResponse(400, text='<html>Bad Request</html>'))

    with pytest.raises(RuntimeError, match='400'):
        fetch_issues.fetch(config)
