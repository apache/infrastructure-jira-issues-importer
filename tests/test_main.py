from conftest import FakeResponse


def test_end_to_end_import(sample_xml, workdir, monkeypatch, fake_http):
    import main
    (workdir / 'labels_mapping.txt').write_text('wish=improvement\n')
    env = {'FILE_PATHS': sample_xml, 'JIRA_PROJECT_NAME': 'TEST', 'JIRA_URL': 'https://jira.example.org',
           'GITHUB_NAME': 'acme', 'GITHUB_REPO': 'widgets', 'GITHUB_ACCESS_TOKEN': 't', 'ASSUME_YES': 'true',
           'COMPONENT_LABEL_PREFIX': 'component: '}
    for name, value in env.items():
        monkeypatch.setenv('JIRA_MIGRATION_' + name, value)
    monkeypatch.setattr('builtins.input', lambda *_: (_ for _ in ()).throw(AssertionError('prompted')))

    fake_http.on('GET', '/milestones', lambda url, **kw: FakeResponse(json_data=[{'title': '1.0.0', 'number': 3}]))
    fake_http.on('POST', '/milestones', lambda url, json, **kw: FakeResponse(201, {'number': 9}))
    fake_http.on('POST', '/labels', lambda url, **kw: FakeResponse(201, {}))
    numbers = iter(range(50, 60))
    fake_http.on('POST', '/import/issues', lambda url, **kw: FakeResponse(202, {'url': f'https://api/status/{next(numbers)}'}))
    fake_http.on('GET', '/status/', lambda url, **kw: FakeResponse(
        200, {'status': 'imported', 'issue_url': 'https://api.github.com/repos/acme/widgets/issues/' + url.rsplit('/', 1)[1]}))

    main.main()

    uploads = [c[2]['json']['issue'] for c in fake_http.calls_to('POST', '/import/issues')]
    assert [u['milestone'] for u in uploads if 'milestone' in u] == [3, 9]
    assert 'component: tokenizer' in uploads[0]['labels']
    assert set(uploads[3]['labels']) == {'improvement', 'imported-jira-issue'}
    assert all(c[1].startswith('https://api.github.com/repos/acme/widgets/') for c in fake_http.calls
               if 'status' not in c[1])
    assert (workdir / 'jira-keys-to-github-id.txt').read_text().split() == \
        ['TEST-1:50', 'TEST-2:51', 'TEST-3:52', 'TEST-4:53']
