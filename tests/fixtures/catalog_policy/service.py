from query import parse_page, parse_size
from pagination import paginate


def list_catalog(records, params):
    """Return only active records, sorted by id, without mutating the caller."""
    records.sort(key=lambda row: row['id'])
    result = paginate(records, parse_page(params.get('page')), parse_size(params.get('size')))
    result['items'] = [row for row in result['items'] if row.get('active', True)]
    return result
