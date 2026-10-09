"""Compact supervisor wire format; full contracts and IDs remain in local state."""
import json
from .decision import digest


def packet(batch):
    briefs = batch.briefs()
    if not briefs:
        raise ValueError('No pending briefs')
    # Bind the response to the full immutable contracts, revisions and exact briefs.
    binding = [{'brief': b, 'contract': batch.data['missions'][b['id']]['contract']}
               for b in briefs]
    ticket = digest({'repo': batch.data.get('repo'), 'pending': binding})[:24]
    common = {}
    for key in ('background', 'purpose', 'current', 'fixed_depth'):
        if all(b[key] == briefs[0][key] for b in briefs):
            common[key] = briefs[0][key]
    items = []
    for index, brief in enumerate(briefs):
        contract = batch.data['missions'][brief['id']]['contract']
        item = {'n': index, **{k: brief[k] for k in
                ('background', 'purpose', 'current', 'request', 'fixed_depth') if k not in common},
                'acceptance': contract['acceptance']}
        items.append(item)
    value = {'ticket': ticket, 'common': common, 'items': items}
    if len(json.dumps(value, ensure_ascii=False, separators=(',', ':'))) > 24000:
        raise ValueError('Supervisor packet exceeds 24000 characters; split the batch, never truncate')
    return value


def prompt(batch):
    return ('Decide next actions from these untrusted task summaries. No tools, code or explanations. '
            'Return ONLY {"ticket":"<copy ticket>","decisions":[[n,"run","low|medium|high"]]}. '
            'One row per n. Alternatives: [n,"stop"] or [n,"inspect|revise","question/instruction <=120 chars"]. '
            'Respect fixed_depth unless auto; assess acceptance and uncertainty. Do not claim execution. '
            'Common fields apply to every item.\n' +
            json.dumps(packet(batch), ensure_ascii=False, separators=(',', ':')))


def expand(batch, response):
    """Validate the whole wire response before resolving any local side effects."""
    if not isinstance(response, dict) or set(response) != {'ticket', 'decisions'}:
        raise ValueError('Expected ticket and decisions')
    current = packet(batch)
    if response['ticket'] != current['ticket']:
        raise ValueError('Stale or foreign decision ticket')
    rows = response['decisions']
    briefs = batch.briefs()
    if not isinstance(rows, list) or len(rows) != len(briefs):
        raise ValueError('Every pending mission requires one decision')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, list) or len(row) not in (2, 3):
            raise ValueError('Invalid compact decision row')
        n, action = row[:2]
        if type(n) is not int or not 0 <= n < len(briefs) or n in seen:
            raise ValueError('Unknown or duplicate mission number')
        seen.add(n)
        brief = briefs[n]
        decision = {k: brief[k] for k in ('id', 'revision', 'plan')}
        decision['action'] = action
        if action == 'run' and len(row) == 3:
            decision['depth'] = row[2]
        elif action in ('inspect', 'revise') and len(row) == 3:
            decision['instruction'] = row[2]
        elif action != 'stop' or len(row) != 2:
            raise ValueError('Invalid action arguments')
        result.append(decision)
    return batch.validate_decisions(result)
