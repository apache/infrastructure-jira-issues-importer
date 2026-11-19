class LabelColourSelector:
    """Picks the colour for newly created GitHub labels (existing labels are not changed)."""

    _COLOURS = {
        'bug': 'ee4035',
        'epic': 'ddf4dd',
    }
    _ENHANCEMENT = ('rfe', 'story', 'enhancement', 'improvement', 'new feature', 'feature')
    _DEFAULT = 'ededed'

    def __init__(self, project):
        self._project = project

    def get_colour(self, label):
        label = label.lower()
        if label in self._ENHANCEMENT:
            return '7bc043'
        return self._COLOURS.get(label, self._DEFAULT)
