from lxml import objectify
import os
import glob


def _read_config_lines(path):
    """Returns the non-blank, non-comment (#) lines of a file, or None if it does not exist."""
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as file:
        lines = (line.strip() for line in file)
        return [line for line in lines if line and not line.startswith('#')]


def fetch_labels_mapping(path="labels_mapping.txt"):
    """
    Reads ``jira label=github label`` lines (keys are matched lower case).
    A missing file means "no mapping". An empty value drops the label.
    """
    mapping = {}
    for line in _read_config_lines(path) or []:
        key, sep, value = line.partition('=')
        if sep:
            mapping[key.strip().lower()] = value.strip()
    return mapping


def fetch_allowed_labels(path="allowed_labels.txt"):
    """
    Reads one allowed GitHub label per line. A missing file returns None, meaning every
    label is allowed.
    """
    lines = _read_config_lines(path)
    return None if lines is None else set(lines)


def _map_label(label, labels_mapping):
    return labels_mapping.get(label.lower(), label) if label is not None else None


def _is_label_approved(label, approved_labels):
    return approved_labels is None or label in approved_labels


def sanitize_github_label(label):
    """GitHub rejects label names containing commas, e.g. the Jira component "Build, Packaging and Test"."""
    return ' '.join(label.replace(',', ' ').split())


def convert_label(label, labels_mappings, approved_labels):
    """
    Maps a Jira label to its GitHub label; returns None if it is dropped or not allowed.
    Commas are removed from the result, as GitHub does not allow them in label names.
    """
    mapped_label = _map_label(label, labels_mappings)

    if mapped_label and _is_label_approved(mapped_label, approved_labels):
        return sanitize_github_label(mapped_label) or None
    return None


def read_xml_file(file_path):
    # read bytes: lxml rejects str input that carries an <?xml encoding=...?> declaration
    with open(file_path, 'rb') as file:
        return objectify.fromstring(file.read())


def read_xml_files(file_path):
    files = list()
    for file_name in file_path.split(';'):
        if os.path.isdir(file_name):
            xml_files = glob.glob(file_name + '/*.xml')
            for file in xml_files:
                files.append(read_xml_file(file))
        else:
            files.append(read_xml_file(file_name))

    return files
