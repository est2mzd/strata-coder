"""Task-scoped reasoning choices. Auto is resolved by the supervising Cursor agent."""
LEVELS = ('low', 'medium', 'high')

def resolve(config, depth=None, reasoning_effort=None, depth_reason='', max_output_tokens=None):
    selected = depth if depth is not None else config.get('depth', 'low')
    if selected not in ('auto', *LEVELS):
        raise ValueError('depth must be auto, low, medium or high')
    if not isinstance(depth_reason, str) or len(depth_reason) > 500:
        raise ValueError('depth_reason must be a string of at most 500 characters')
    if selected == 'auto':
        if reasoning_effort not in LEVELS or not depth_reason.strip():
            raise ValueError('auto requires Cursor to choose reasoning_effort=low|medium|high and depth_reason; no extra classification call')
    else:
        if reasoning_effort is not None and reasoning_effort != selected:
            raise ValueError('Explicit depth takes precedence; reasoning_effort conflicts')
        reasoning_effort = selected
    tokens = max_output_tokens if max_output_tokens is not None else config.get('max_output_tokens', 2048)
    if type(tokens) is not int or not 128 <= tokens <= 8192:
        raise ValueError('max_output_tokens must be an integer in 128..8192')
    return dict(depth=selected, reasoning_effort=reasoning_effort,
                depth_reason=depth_reason.strip() or 'Explicit depth selection', max_output_tokens=tokens)
