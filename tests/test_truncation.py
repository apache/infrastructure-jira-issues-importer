from lxml import objectify

from project import Project, truncate_html


def test_short_text_is_untouched():
    assert truncate_html('<p>hi</p>', 100, 'https://j/x') == '<p>hi</p>'


def test_long_text_is_cut_with_link_to_full_text():
    text = '<p>' + 'a' * 500 + '</p>'
    result = truncate_html(text, 200, 'https://jira.example.org/browse/TEST-1')

    assert len(result) <= 200
    assert result.startswith('<p>aaa')
    assert 'truncated' in result
    assert 'href="https://jira.example.org/browse/TEST-1"' in result


def test_cut_never_leaves_a_partial_tag_or_open_pre_block():
    text = '<pre>' + 'x' * 100 + '<b>bold</b>' + 'y' * 500 + '</pre>'
    result = truncate_html(text, 220, 'https://j/x')

    note_start = result.index('<i>[')
    content = result[:note_start]
    assert content.count('<pre>') == content.count('</pre>')
    assert content.rstrip().endswith('</pre>')
    assert len(result) <= 220

    partial = truncate_html('<p>' + 'x' * 90 + '<a href="https://example.org/very/long">link</a>' + 'z' * 200, 150, 'u')
    assert '<a href="https' not in partial.split('<i>[')[0]


def _item(xml):
    return objectify.fromstring(xml)


ITEM = '''<item><title>[TEST-7] Big</title><project key="TEST">Test</project><key>TEST-7</key>
<description>{description}</description><type>Bug</type><statusCategory id="2"/>
<reporter username="bob">Bob</reporter><labels/>
<created>Mon, 3 Nov 2025 10:00:00 +0000</created><updated>Mon, 3 Nov 2025 10:00:00 +0000</updated>
<comments><comment id="77" author="carol" created="Mon, 3 Nov 2025 12:00:00 +0000">{comment}</comment></comments>
</item>'''


def test_huge_description_and_comment_fit_github_limits(make_config):
    project = Project(make_config(max_text_length=1000))
    project.add_item(_item(ITEM.format(description='d' * 5000, comment='c' * 5000)))
    issue = project.get_issues()[0]

    assert len(issue['body']) <= 1000
    # metadata block survives truncation of the description
    assert issue['body'].rstrip().endswith('</details>')
    assert 'href="https://jira.example.org/browse/TEST-7"' in issue['body']

    comment = issue['comments'][0]['body']
    assert len(comment) <= 1000
    assert 'focusedCommentId=77' in comment
