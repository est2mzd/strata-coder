"""Pagination is one-based; callers retain ownership of input records."""
def paginate(records, page, size):
    start = page * size
    return {"items": records[start:start + size], "total": len(records),
            "has_next": start + size <= len(records)}
