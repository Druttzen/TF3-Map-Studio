"""Read alignment fields without retaining the converter's large source graphs."""
from pathlib import Path
import ijson
from ijson.common import ObjectBuilder

FIELDS = frozenset({'dataset', 'input', 'bounds', 'mapSize', 'settings',
                    'sourceSha256', 'luaSha256', 'alignment', 'output', 'report',
                    'edges', 'sceneryItems', 'placeLabels', 'waterFeatures',
                    'format', 'converterDataset'})


def read_fields(path):
    """Validate the entire JSON stream, materializing only alignment metadata."""
    result = {}
    with Path(path).open('rb') as source:
        # The producer and older Windows-edited reports may include a UTF-8 BOM.
        if source.read(3) != b'\xef\xbb\xbf':
            source.seek(0)
        events = iter(ijson.basic_parse(source, use_float=True))
        try:
            if next(events, None) != ('start_map', None):
                raise ValueError('The converter report must be a JSON object.')
            seen = set()
            retained_events = 0
            while True:
                event, key = next(events)
                if event == 'end_map':
                    break
                if event != 'map_key' or key in seen:
                    raise ValueError('The converter report contains an invalid or repeated field.')
                seen.add(key)
                if len(seen) > 10000:
                    raise ValueError('The converter report contains too many metadata fields.')
                builder = ObjectBuilder() if key in FIELDS else None
                event, value = next(events)
                depth = 0
                while True:
                    if event in ('start_map', 'start_array'):
                        depth += 1
                    elif event in ('end_map', 'end_array'):
                        depth -= 1
                    if depth > 128:
                        raise ValueError('The converter report is nested too deeply.')
                    if builder is not None:
                        retained_events += 1
                        if retained_events > 100000:
                            raise ValueError('The converter alignment metadata is too large.')
                        builder.event(event, value)
                    if depth == 0:
                        break
                    event, value = next(events)
                if builder is not None:
                    result[key] = builder.value
            # Do not accept an incomplete or malformed tail in skipped source data.
            if next(events, None) is not None:
                raise ValueError('Unexpected content after the converter report.')
        except (ijson.JSONError, StopIteration, UnicodeError) as exc:
            raise ValueError('Invalid or incomplete JSON in the converter report. Select the complete .report.json or import-report.json produced by the OSM converter.') from exc
    return result
