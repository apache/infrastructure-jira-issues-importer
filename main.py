#!/usr/bin/env python3
"""
Imports a Jira XML export into GitHub issues.

All settings are read from JIRA_MIGRATION_* environment variables (see config.py and the
README); missing required settings are asked for interactively.

Steps:
  1. Create any milestones
  2. Create any labels
  3. Create each issue with comments, linking them to milestones and labels
"""

from config import load_config
from importer import Importer
from labelcolourselector import LabelColourSelector
from project import Project
from utils import read_xml_files


def main():
    config = load_config(required=('file_paths', 'github_account', 'github_repo', 'github_token'))

    project = Project(config)
    for f in read_xml_files(config.file_paths):
        for item in f.channel.item:
            project.add_item(item)

    project.prettify()

    if not config.assume_yes:
        input('Press any key to begin...')

    importer = Importer(config, project)
    print('Creating issues with the', 'regular Issues API' if importer.api_mode == 'rest' else 'Issue Import API')
    importer.import_milestones()

    if config.start_from == 0:
        importer.import_labels(LabelColourSelector(project))

    importer.import_issues(config.start_from)


if __name__ == '__main__':
    main()
