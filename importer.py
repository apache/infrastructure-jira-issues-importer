import time
from html import escape
from urllib.parse import quote

import requests

from utils import fetch_labels_mapping, fetch_allowed_labels, convert_label


class Importer:
    _DEFAULT_TIME_OUT = 120.0
    _MAX_STATUS_CHECKS = 100

    def __init__(self, config, project):
        self.config = config
        self.project = project
        self.github_url = config.github_repo_api_url
        self.headers = {
            'Accept': 'application/vnd.github.golden-comet-preview+json',
            'Authorization': f'token {config.github_token}'
        }

        self.labels_mapping = fetch_labels_mapping(config.labels_mapping_file)
        self.approved_labels = fetch_allowed_labels(config.allowed_labels_file)
        self.milestone_numbers = {}  # milestone title -> GitHub milestone number
        self._imported_keys = {issue['key'] for issue in project.get_issues()}
        self.api_mode = config.resolved_github_import_api

    def _get_all_pages(self, url):
        """GETs a paginated GitHub list resource, following the Link: rel="next" headers."""
        results = []
        while url:
            response = requests.get(url, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
            if response.status_code != 200:
                raise RuntimeError(f'Failed to list {url}: {response.status_code} {response.text}')
            results.extend(response.json())
            url = response.links.get('next', {}).get('url')
        return results

    def import_milestones(self):
        """
        Maps the gathered Jira fix versions to GitHub milestones (matched by title),
        creating the missing ones, and remembers the GitHub milestone numbers in
        ``milestone_numbers``.
        """
        milestone_url = self.github_url + '/milestones'
        milestones = self.project.get_milestones()
        print('Importing milestones...', milestone_url)

        for existing in self._get_all_pages(milestone_url + '?state=all&per_page=100'):
            if existing['title'] in milestones:
                self.milestone_numbers[existing['title']] = existing['number']
                print(existing['title'], 'found:', existing['number'])

        for title in milestones:
            if title in self.milestone_numbers:
                continue
            r = requests.post(milestone_url, json={'title': title}, headers=self.headers,
                              timeout=Importer._DEFAULT_TIME_OUT)
            if r.status_code != 201:
                raise RuntimeError(f'Failed to create milestone {title}: {r.status_code} {r.text}')
            self.milestone_numbers[title] = r.json()['number']
            print(title, 'created:', self.milestone_numbers[title])

    def import_labels(self, colour_selector):
        """
        Creates the final GitHub labels (already mapped and filtered by the project).
        Labels that already exist in the repository are left untouched.
        """
        label_url = self.github_url + '/labels'
        print('Importing labels...', label_url)

        for label in self.project.get_all_labels().keys():
            data = {'name': label, 'color': colour_selector.get_colour(label)}
            r = requests.post(label_url, json=data, headers=self.headers, timeout=Importer._DEFAULT_TIME_OUT)
            if r.status_code == 201:
                print('created label', label)
            elif r.status_code == 422 and 'already_exists' in str(r.json()):
                print('label exists', label)
            else:
                print('Failure importing label ' + label, r.status_code, r.text)

    _ISSUE_FIELDS = ('title', 'body', 'created_at', 'updated_at', 'closed', 'closed_at', 'labels', 'milestone')
    _COMMENT_FIELDS = ('body', 'created_at')

    def _already_imported(self):
        """Jira keys listed in the mapping output file of a previous (partial) run."""
        try:
            with open(self.config.mapping_output_file, encoding='utf-8') as f:
                return {line.split(':', 1)[0].strip() for line in f if ':' in line}
        except FileNotFoundError:
            return set()

    def import_issues(self, start_from_count=0):
        """
        Imports the issues (with comments) in order. Issues before index ``start_from_count``
        and issues already listed in the mapping output file are skipped, so an aborted run
        can simply be restarted.
        """
        print('Importing issues...')
        already_imported = self._already_imported()

        for count, issue in enumerate(self.project.get_issues()):
            if count < start_from_count:
                continue
            if issue['key'] in already_imported:
                print('Skipping already imported', issue['key'])
                continue
            print('Index =', count)
            if self.api_mode == 'rest':
                self.create_issue_with_comments(*self._to_payload(issue))
            else:
                self.import_issue_with_comments(*self._to_payload(issue))

    def _to_payload(self, issue):
        """Builds the Issue Import API payload (only fields the API accepts) for one issue."""
        issue = dict(issue, comments=list(issue['comments']))
        self.convert_relationships_to_comments(issue)

        payload = {k: issue[k] for k in Importer._ISSUE_FIELDS if k in issue}
        payload['labels'] = [label for label in issue['labels'] if label]
        if 'milestone_name' in issue:
            title = issue['milestone_name']
            if title not in self.milestone_numbers:
                raise RuntimeError(f'GitHub milestone for "{title}" ({issue["key"]}) is unknown; '
                                   f'run import_milestones() first')
            payload['milestone'] = self.milestone_numbers[title]
        comments = [{k: c[k] for k in Importer._COMMENT_FIELDS if k in c} for c in issue['comments']]
        return issue['key'], payload, comments

    def import_issue_with_comments(self, jira_key, issue, comments):
        """
        Imports a single issue with its comments into GitHub.
        Importing via GitHub's normal Issue API quickly triggers anti-abuse rate limits.
        So their unofficial Issue Import API is used instead:
        https://gist.github.com/jonmagic/5282384165e0f86ef105
        The issue is pushed asynchronously, then its import status is polled until done.
        The resulting "JIRA-KEY:github number" is appended to the mapping output file.
        """
        print('Issue', jira_key, 'labels', issue['labels'], 'comments', len(comments))

        response = self.upload_github_issue(issue, comments)
        status_url = response.json()['url']
        gh_issue_url = self.wait_for_issue_creation(status_url).json()['issue_url']
        gh_issue_id = int(gh_issue_url.split('/')[-1])

        with open(self.config.mapping_output_file, 'a', encoding='utf-8') as f:
            f.write(f'{jira_key}:{gh_issue_id}\n')
        return gh_issue_id

    def upload_github_issue(self, issue, comments):
        """
        Uploads a single issue to GitHub asynchronously with the Issue Import API.
        """
        issue_url = self.github_url + '/import/issues'
        issue_data = {'issue': issue, 'comments': comments}
        response = requests.post(issue_url, json=issue_data, headers=self.headers, 
            timeout=Importer._DEFAULT_TIME_OUT)
        if response.status_code == 202:
            return response
        elif response.status_code == 422:
            raise RuntimeError(
                "Initial import validation failed for issue '{}' due to the "
                "following errors:\n{}".format(issue['title'], response.json())
            )
        else:
            hint = ('\nThe Issue Import API needs a classic token; for a fine-grained token set '
                    'JIRA_MIGRATION_GITHUB_IMPORT_API=rest.' if response.status_code == 403 else '')
            raise RuntimeError(
                "Failed to POST issue: '{}' due to unexpected HTTP status code: {}\nerrors:\n{}{}"
                .format(issue['title'], response.status_code, response.json(), hint)
            )

    def wait_for_issue_creation(self, status_url):
        """
        Check the status of a GitHub issue import.
        If the status is 'pending', it sleeps, then rechecks until the status is
        either 'imported' or 'failed'.
        """
        for _ in range(Importer._MAX_STATUS_CHECKS):
            time.sleep(3)
            response = requests.get(status_url, headers=self.headers,
                                    timeout=Importer._DEFAULT_TIME_OUT)
            if response.status_code == 404:
                continue
            elif response.status_code != 200:
                raise RuntimeError(
                    "Failed to check GitHub issue import status url: {} due to unexpected HTTP status code: {}"
                    .format(status_url, response.status_code)
                )

            status = response.json()['status']
            if status != 'pending':
                break
        else:
            raise RuntimeError(f'GitHub issue import {status_url} did not finish in time')

        if status == 'imported':
            print("Imported Issue:", response.json()['issue_url'].replace('api.github.com/repos/', 'github.com/'))
        elif status == 'failed':
            raise RuntimeError(
                "Failed to import GitHub issue due to the following errors:\n{}"
                .format(response.json())
            )
        else:
            raise RuntimeError(
                "Status check for GitHub issue import returned unexpected status: '{}'"
                .format(status)
            )
        return response

    # --- regular REST Issues API (works with fine-grained tokens) ---

    _MAX_RATE_LIMIT_RETRIES = 10

    def _write(self, method, url, json):
        """
        Sends a write request, pausing ``github_write_delay`` first. On a (secondary) rate
        limit it waits as long as GitHub asks (retry-after / x-ratelimit-reset, at least a
        minute) and retries.
        """
        for _ in range(Importer._MAX_RATE_LIMIT_RETRIES):
            time.sleep(self.config.github_write_delay)
            response = getattr(requests, method)(url, json=json, headers=self.headers,
                                                 timeout=Importer._DEFAULT_TIME_OUT)
            if response.status_code in (403, 429) and self._is_rate_limited(response):
                wait = self._rate_limit_wait(response)
                print(f'Rate limited by GitHub, waiting {wait} seconds...')
                time.sleep(wait)
                continue
            return response
        raise RuntimeError(f'Still rate limited by GitHub after {Importer._MAX_RATE_LIMIT_RETRIES} retries: {url}')

    @staticmethod
    def _is_rate_limited(response):
        return ('retry-after' in response.headers or response.headers.get('x-ratelimit-remaining') == '0'
                or 'rate limit' in (response.text or '').lower())

    @staticmethod
    def _rate_limit_wait(response):
        if 'retry-after' in response.headers:
            return max(int(response.headers['retry-after']), 1)
        if response.headers.get('x-ratelimit-remaining') == '0' and 'x-ratelimit-reset' in response.headers:
            return max(int(response.headers['x-ratelimit-reset']) - int(time.time()), 0) + 1
        return 60

    @staticmethod
    def _with_original_dates(issue):
        """The REST API cannot backdate issues, so the original dates are added to the details block."""
        dates = f'\n<li><b>created</b>: {issue["created_at"]}' if issue.get('created_at') else ''
        end = '\n</ul></i>\n</details>'
        body = issue['body']
        if end in body:
            index = body.rindex(end)
            return body[:index] + dates + body[index:]
        return body + dates

    def create_issue_with_comments(self, jira_key, issue, comments):
        """
        Creates a single issue with the regular REST Issues API: the issue, then each comment,
        then closes it if it is done in Jira. Unlike the Import API this works with fine-grained
        tokens, but creation dates cannot be set (they are noted in the text instead) and
        GitHub sends the usual notifications. The "JIRA-KEY:github number" is appended to the
        mapping output file once the issue is complete.
        """
        print('Issue', jira_key, 'labels', issue['labels'], 'comments', len(comments))

        data = {'title': issue['title'], 'body': self._with_original_dates(issue), 'labels': issue['labels']}
        if 'milestone' in issue:
            data['milestone'] = issue['milestone']
        response = self._write('post', self.github_url + '/issues', data)
        if response.status_code != 201:
            raise RuntimeError(f"Failed to create issue '{issue['title']}': {response.status_code} {response.text}")
        number = response.json()['number']
        html_url = response.json().get('html_url', number)

        for comment in comments:
            body = comment['body']
            if comment.get('created_at'):
                body = f'<i>{comment["created_at"]}</i> ' + body
            r = self._write('post', f'{self.github_url}/issues/{number}/comments', {'body': body})
            if r.status_code != 201:
                raise RuntimeError(f'Failed to add a comment to issue {html_url} ({jira_key}): '
                                   f'{r.status_code} {r.text}\nRemove the issue before rerunning, '
                                   f'as it is not in the mapping file yet.')

        if issue.get('closed'):
            r = self._write('patch', f'{self.github_url}/issues/{number}',
                            {'state': 'closed', 'state_reason': 'completed'})
            if r.status_code != 200:
                raise RuntimeError(f'Failed to close issue {html_url} ({jira_key}): {r.status_code} {r.text}')

        print('Created Issue:', html_url)
        with open(self.config.mapping_output_file, 'a', encoding='utf-8') as f:
            f.write(f'{jira_key}:{number}\n')
        return number

    def _issue_href(self, key):
        """
        Links to the GitHub issue (searching the key in the title) when the issue is part of
        this import, otherwise to the issue in Jira.
        """
        if key in self._imported_keys:
            return f'{self.config.github_repo_url}/issues?q=' + quote(f'is:issue in:title "{key}"', safe='')
        return f'{self.project.jiraBaseUrl}/browse/{quote(key)}'

    def convert_relationships_to_comments(self, issue):
        """Turns the collected Jira issue links and the epic link into comments."""
        links = issue.pop('links', [])
        if links:
            items = ''.join(f'\n<li>{escape(description)} <a href="{self._issue_href(key)}">{escape(key)}</a></li>'
                            for description, key in links)
            issue['comments'].append({'body': f'<i>Jira issue links:</i>\n<ul>{items}\n</ul>'})

        epic_link = issue.pop('epic-link', None)
        if epic_link:
            # format is parsed by post_process_issues.sh
            issue['comments'].append(
                {'body': f'<i>[Epic: <a href="{self._issue_href(epic_link)}">{escape(epic_link)}</a>]</i>'})
