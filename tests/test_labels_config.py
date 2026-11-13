from utils import fetch_labels_mapping, fetch_allowed_labels, convert_label


def test_allowed_labels_can_be_queried_repeatedly(workdir):
    (workdir / 'allowed.txt').write_text('bug\nimprovement\n\ntask\n')
    allowed = fetch_allowed_labels(str(workdir / 'allowed.txt'))

    # the old implementation returned a generator, which is exhausted after the first lookup
    assert convert_label('task', {}, allowed) == 'task'
    assert convert_label('bug', {}, allowed) == 'bug'
    assert convert_label('bug', {}, allowed) == 'bug'
    assert convert_label('unknown', {}, allowed) is None


def test_mapping_tolerates_blank_lines_comments_and_spaces(workdir):
    (workdir / 'mapping.txt').write_text(
        '# types\n'
        'new feature = new feature\n'
        '\n'
        'build, packaging and test=component: build\n'
        'help-wanted=help wanted\n')
    mapping = fetch_labels_mapping(str(workdir / 'mapping.txt'))

    assert mapping == {'new feature': 'new feature',
                       'build, packaging and test': 'component: build',
                       'help-wanted': 'help wanted'}


def test_mapping_values_may_contain_equals_sign(workdir):
    (workdir / 'mapping.txt').write_text('a=b=c\n')
    assert fetch_labels_mapping(str(workdir / 'mapping.txt')) == {'a': 'b=c'}


def test_missing_files_mean_no_mapping_and_everything_allowed(workdir):
    mapping = fetch_labels_mapping(str(workdir / 'nope.txt'))
    allowed = fetch_allowed_labels(str(workdir / 'nope.txt'))

    assert mapping == {}
    assert allowed is None
    assert convert_label('anything', mapping, allowed) == 'anything'


def test_mapping_is_applied_before_allow_list(workdir):
    allowed = {'component: build'}
    mapping = {'build, packaging and test': 'component: build'}

    assert convert_label('build, packaging and test', mapping, allowed) == 'component: build'
    assert convert_label('wsd', mapping, allowed) is None


def test_mapping_to_empty_value_drops_label():
    assert convert_label('gsoc2015', {'gsoc2015': ''}, None) is None


def test_convert_label_removes_commas_rejected_by_github():
    assert convert_label('component: build, packaging and test', {}, None) == 'component: build packaging and test'
    assert convert_label('a,b', {}, None) == 'a b'
    assert convert_label('x', {'x': 'mapped, label'}, None) == 'mapped label'
    assert convert_label(',', {}, None) is None
