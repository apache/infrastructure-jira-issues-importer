#!/usr/bin/env python3
"""
Prints every label candidate (issue types, prefixed components and Jira labels) found in the
configured XML export(s), with usage counts, followed by the resulting GitHub labels.
The candidates are exactly the keys to use in the labels mapping file.
"""

from config import load_config
from project import Project
from utils import read_xml_files


def main():
    config = load_config(required=('file_paths',))
    project = Project(config)

    for f in read_xml_files(config.file_paths):
        for item in f.channel.item:
            project.add_item(item)

    for title, counts in (('Types', project.get_types()), ('Components', project.get_components()),
                          ('Labels', project.get_labels()),
                          ('GitHub labels (after mapping)', project.get_all_labels())):
        print(f'# {title}')
        for key in sorted(counts):
            print(f'{key}  ({counts[key]})')
        print()


if __name__ == '__main__':
    main()
