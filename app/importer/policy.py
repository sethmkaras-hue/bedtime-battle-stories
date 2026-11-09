"""Robots decisions and diagnostics for the pinned Protego parser.

Public can_fetch is authoritative. The small version-specific inspection below
only explains its winning rule; changing it cannot grant access.
"""

from protego import Protego
from protego._utils import _quote_path


def decision(parser, url, user_agent):
    allowed = parser.can_fetch(url, user_agent)
    rules = parser._get_matching_rule_set(user_agent)
    matched = (
        next((r for r in rules._rules if r.value.match(_quote_path(url))), None)
        if rules
        else None
    )
    return {
        "allowed": allowed,
        "robots_group": rules.user_agent if rules else None,
        "robots_rule": f"{matched.field.title()}: {matched.value._pattern}"
        if matched
        else None,
    }
