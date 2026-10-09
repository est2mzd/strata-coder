"""Parse pagination values received from an HTTP query."""
def parse_page(value, default=1):
    if value is None:
        return default
    return int(value)


def parse_size(value, default=10, maximum=50):
    if value is None:
        return default
    return min(int(value), maximum)
