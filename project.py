import re
from collections import defaultdict
from dateutil.parser import parse
from datetime import datetime
from html import escape
from urllib.parse import quote

from utils import fetch_labels_mapping, fetch_allowed_labels, convert_label


def _child(item, name):
    """Returns the first child element called ``name`` or None if it does not exist."""
    return item.find(name)


def _children(item, path):
    """Returns all elements matching ``path`` (may be empty)."""
    return item.findall(path)


_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr'}
_TAG = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(/?)>')


def _unclosed_tags(html):
    stack = []
    for closing, name, self_closing in _TAG.findall(html):
        name = name.lower()
        if self_closing or name in _VOID_TAGS:
            continue
        if not closing:
            stack.append(name)
        elif name in stack:
            while stack.pop() != name:
                pass
    return stack


def truncate_html(text, limit, full_text_url):
    """
    Cuts ``text`` to at most ``limit`` characters (GitHub rejects longer bodies/comments),
    without leaving a partial tag/entity, closes still open tags (e.g. a <pre> block) and
    appends a note linking to the full text.
    """
    if len(text) <= limit:
        return text
    note = (f'\n\n<i>[truncated, see the full text in Jira: '
            f'<a href="{full_text_url}">{escape(full_text_url)}</a>]</i>')
    budget = limit - len(note)
    while budget > 0:
        cut = text[:budget]
        if cut.rfind('<') > cut.rfind('>'):
            cut = cut[:cut.rfind('<')]
        cut = re.sub(r'&#?\w*$', '', cut)
        closers = ''.join(f'</{name}>' for name in reversed(_unclosed_tags(cut)))
        result = cut + closers + note
        if len(result) <= limit:
            return result
        budget -= len(result) - limit
    return note[:limit]


class Project:

    def __init__(self, config):
        self.config = config
        self.name = config.jira_project
        self.doneStatusCategoryId = str(config.jira_done_id)
        self.jiraBaseUrl = config.jira_url_normalized
        self._project = {'Milestones': defaultdict(int), 'Components': defaultdict(int),
                         'Labels': defaultdict(int), 'Types': defaultdict(int),
                         'GitHubLabels': defaultdict(int), 'Issues': []}

        self.labels_mapping = fetch_labels_mapping(config.labels_mapping_file)
        self.approved_labels = fetch_allowed_labels(config.allowed_labels_file)

    def get_milestones(self):
        return self._project['Milestones']

    def get_components(self):
        return self._project['Components']

    def get_issues(self):
        return self._project['Issues']

    def get_types(self):
        return self._project['Types']

    def get_all_labels(self):
        """The final GitHub labels (after mapping and allow list) with their usage count."""
        return self._project['GitHubLabels']

    def get_labels(self):
        """The raw Jira labels (lower-cased, i.e. mapping file keys) with their usage count."""
        return self._project['Labels']

    def add_item(self, item):
        itemProject = self._projectFor(item)
        if itemProject != self.name:
            print('Skipping item ' + item.key.text + ' for project ' +
                  itemProject + ' current project: ' + self.name)
            return

        self._append_item_to_project(item)

        self._add_milestone(item)

        self._add_labels(item)

        self._add_comments(item)

        self._add_relationships(item)

    def prettify(self):
        def hist(h):
            for key in h.keys():
                print(('%30s (%5d): ' + h[key] * '#') % (key, h[key]))
            print()

        print(self.name + ':\n  Milestones:')
        hist(self._project['Milestones'])
        print('  Types:')
        hist(self._project['Types'])
        print('  Components:')
        hist(self._project['Components'])
        print('  Labels:')
        hist(self._project['Labels'])
        print('  GitHub labels (after mapping):')
        hist(self._project['GitHubLabels'])
        print('Total Issues to Import: %d' % len(self._project['Issues']))

    def _projectFor(self, item):
        try:
            result = item.project.get('key')
        except AttributeError:
            result = item.key.text.split('-')[0]
        return result

    def _user_link(self, user):
        username = user.get('username') or str(user)
        return ('<a title="' + escape(str(user)) + '" href="' + self.jiraBaseUrl
                + '/secure/ViewProfile.jspa?name=' + quote(username) + '">' + escape(username) + '</a>')

    def _append_item_to_project(self, item):
        closed = str(item.statusCategory.get('id')) == self.doneStatusCategoryId
        resolved = _child(item, 'resolved')
        closed_at = ''
        if closed and resolved is not None and resolved.text:
            closed_at = self._convert_to_iso(resolved.text)

        description = _child(item, 'description')
        if description is None or not (description.text or '').strip():
            description_html = 'No Description'
        else:
            description_html = self._htmlentitydecode(description.text)

        # metadata: original author & link
        summary = item.title.text[item.title.text.index("]") + 2:]
        reporter = _child(item, 'reporter')
        body = '\n\n---\n<details><summary><i>'
        if reporter is not None:
            body = body + 'Originally reported by ' + self._user_link(reporter) + ', '
        body = body + 'imported from: <a href="' + self.jiraBaseUrl + '/browse/' + item.key.text + '" target="_blank">' + escape(summary) + '</a></i></summary>'
        body = body + '\n<i><ul>'

        assignee = _child(item, 'assignee')
        if assignee is not None and assignee.get('username') not in (None, '-1'):
            body = body + '\n<li><b>assignee</b>: ' + self._user_link(assignee)
        for field in ('status', 'priority', 'resolution'):
            value = _child(item, field)
            if value is not None and value.text:
                body = body + '\n<li><b>' + field + '</b>: ' + escape(value.text)
        if resolved is not None and resolved.text:
            body = body + '\n<li><b>resolved</b>: ' + self._convert_to_iso(resolved.text)
        attachments = [a for a in _children(item, 'attachments/attachment') if a.get('id') and a.get('name')]
        if attachments:
            body = body + '\n<li><b>attachments</b>: ' + ', '.join(
                '<a href="' + self.jiraBaseUrl + '/secure/attachment/' + quote(a.get('id')) + '/' + quote(a.get('name'))
                + '">' + escape(a.get('name')) + '</a>' for a in attachments)
        body = body + '\n<li><b>imported</b>: ' + datetime.today().strftime('%Y-%m-%d')
        body = body + '\n</ul></i>\n</details>'
        issue_url = self.jiraBaseUrl + '/browse/' + item.key.text
        body = truncate_html(description_html, self.config.max_text_length - len(body), issue_url) + body

        unique_labels = self._github_labels(item)

        self._project['Issues'].append({'title': item.title.text,
                                        'key': item.key.text,
                                        'body': body,
                                        'created_at': self._convert_to_iso(item.created.text),
                                        'closed_at': closed_at,
                                        'updated_at': self._convert_to_iso(item.updated.text),
                                        'closed': closed,
                                        'labels': unique_labels,
                                        'comments': [],
                                        'links': []
                                        })
        if not self._project['Issues'][-1]['closed_at']:
            del self._project['Issues'][-1]['closed_at']

    def label_candidates(self, item):
        """
        Returns the (kind, candidate label) pairs of an item before mapping. The candidate is
        what has to be used as key in the labels mapping file:
        the lower-cased issue type, the configured component prefix plus the lower-cased
        component, and the lower-cased Jira label.
        """
        candidates = []
        issue_type = _child(item, 'type')
        if issue_type is not None and issue_type.text:
            candidates.append(('type', issue_type.text.strip().lower()))
        if self.config.include_component_in_labels:
            for component in _children(item, 'component'):
                if component.text and component.text.strip():
                    candidates.append(('component', self.config.component_label_prefix + component.text.strip().lower()))
        for label in _children(item, 'labels/label'):
            if label.text and label.text.strip():
                candidates.append(('label', label.text.strip().lower()))
        return candidates

    def _github_labels(self, item):
        """Maps the item's type, components and labels to the final GitHub labels."""
        labels = []
        for _, candidate in self.label_candidates(item):
            converted = convert_label(candidate, self.labels_mapping, self.approved_labels)
            if converted and converted not in labels:
                labels.append(converted)
        if self.config.imported_label and self.config.imported_label not in labels:
            labels.append(self.config.imported_label)
        for label in labels:
            self._project['GitHubLabels'][label] += 1
        return labels

    def _convert_to_iso(self, timestamp):
        dt = parse(timestamp)
        return dt.isoformat()

    def _add_milestone(self, item):
        # GitHub supports a single milestone per issue, so the first fixVersion is used
        versions = [v.text.strip() for v in _children(item, 'fixVersion') if v.text and v.text.strip()]
        if versions:
            self._project['Milestones'][versions[0]] += 1
            # this prop will be replaced by the GitHub milestone number later:
            self._project['Issues'][-1]['milestone_name'] = versions[0]

    def _add_labels(self, item):
        """Collects the raw Jira types, components and labels for the overview (prettify)."""
        kinds = {'type': 'Types', 'component': 'Components', 'label': 'Labels'}
        for kind, candidate in self.label_candidates(item):
            self._project[kinds[kind]][candidate] += 1

    def _add_comments(self, item):
        issue_url = self.jiraBaseUrl + '/browse/' + item.key.text
        for comment in _children(item, 'comments/comment'):
            author = comment.get('author') or 'unknown'
            if author in self.config.skip_comment_authors:
                continue
            header = ('<i><a href="' + self.jiraBaseUrl + '/secure/ViewProfile.jspa?name=' + quote(author) + '">'
                      + escape(author) + '</a>:</i>\n')
            comment_url = issue_url + '?focusedCommentId=' + str(comment.get('id')) + '#comment-' + str(comment.get('id'))
            text = truncate_html(self._htmlentitydecode(comment.text),
                                 self.config.max_text_length - len(header), comment_url)
            self._project['Issues'][-1]['comments'].append(
                {"created_at": self._convert_to_iso(comment.get('created')), "body": header + text})

    def _add_relationships(self, item):
        """
        Collects all Jira issue links (any link type, outward and inward, using Jira's link
        description such as "blocks" or "is blocked by"), subtasks, the parent task and the
        epic link.
        """
        links = self._project['Issues'][-1]['links']
        # Jira's order: per link type, outward before inward
        for linktype in _children(item, 'issuelinks/issuelinktype'):
            for direction in ('outwardlinks', 'inwardlinks'):
                for group in _children(linktype, direction):
                    description = (group.get('description') or linktype.findtext('name') or 'links to').strip()
                    for issuekey in _children(group, 'issuelink/issuekey'):
                        links.append((description, issuekey.text.strip()))

        for subtask in _children(item, 'subtasks/subtask'):
            if subtask.text and subtask.text.strip():
                links.append(('has subtask', subtask.text.strip()))
        parent = _child(item, 'parent')
        if parent is not None and parent.text and parent.text.strip():
            links.append(('is subtask of', parent.text.strip()))

        for customfield in _children(item, 'customfields/customfield'):
            if customfield.get('key') == 'com.pyxis.greenhopper.jira:gh-epic-link':
                epic_key = customfield.findtext('customfieldvalues/customfieldvalue')
                if epic_key and epic_key.strip():
                    self._project['Issues'][-1]['epic-link'] = epic_key.strip()

    def _htmlentitydecode(self, s):
        """
        Prepares Jira's HTML for GitHub. The text already is HTML, so entities must stay
        encoded (decoding would turn escaped code like List&lt;String&gt; into tags).
        Runs of 8 spaces (Jira's export indentation) are removed so GitHub's Markdown
        renderer does not turn them into code blocks.
        """
        if s is None:
            return ''
        return s.replace(' ' * 8, '')
