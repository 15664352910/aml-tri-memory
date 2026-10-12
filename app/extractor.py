"""Rule-based memory extraction at ingestion time.

Deliberately deterministic and dependency-free: persona candidates and
world-model statements are extracted with pattern rules, so Add latency
and hosting cost stay flat and every result is reproducible. The
extraction surface is intentionally small; each rule names its trait or
relation type so downstream governance treats records as typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Extraction:
    persona_candidates: list[tuple[str, str, str]] = field(default_factory=list)  # (trait_type, subject, value)
    world_statements: list[tuple[str, str, str]] = field(default_factory=list)  # (relation, subject, value)


_PERSONA_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("preference", re.compile(r"\bi (?:really )?(like|love|prefer|enjoy)\s+(.+?)[.!?\n]", re.I)),
    ("preference", re.compile(r"\bi (?:really )?(dislike|hate|do not like|don't like)\s+(.+?)[.!?\n]", re.I)),
    ("preference", re.compile(r"\bmy favorite\s+(.+?)\s+is\s+(.+?)[.!?\n]", re.I)),
    ("identity", re.compile(r"\bi am (?:a|an)\s+(.+?)[.!?\n]", re.I)),
    ("identity", re.compile(r"\bi'm (?:a|an)\s+(.+?)[.!?\n]", re.I)),
    ("occupation", re.compile(r"\bi work as (?:a|an)?\s*(.+?)[.!?\n]", re.I)),
    ("occupation", re.compile(r"\bi'm (?:a|an)\s+(.+?)\s+(?:at|for)\s+(.+?)[.!?\n]", re.I)),
    ("habit", re.compile(r"\bi (?:usually|often|always|typically)\s+(.+?)[.!?\n]", re.I)),
    ("goal", re.compile(r"\bi (?:want|plan|hope|intend) to\s+(.+?)[.!?\n]", re.I)),
]

_WORLD_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("affiliation", re.compile(r"\buser works at\s+(.+?)[.!?\n]", re.I)),
    ("location", re.compile(r"\blives in\s+(.+?)[.!?\n]", re.I)),
    ("location", re.compile(r"\bi (?:just )?(?:moved|relocated) to\s+(.+?)[.!?\n]", re.I)),
    ("location", re.compile(r"\bi live in\s+(.+?)[.!?\n]", re.I)),
    ("possession", re.compile(r"\buser(?:'s)?\s+(\w[\w ]*?)\s+is\s+(.+?)[.!?\n]", re.I)),
    ("state", re.compile(r"\bthe\s+(\w[\w ]*?)\s+is\s+(?:now\s+)?(open|closed|ready|done|finished|broken|fixed)[.!?\n]", re.I)),
    ("schedule", re.compile(r"\b(?:meeting|deadline|appointment|call|review)\s+(?:is\s+)?(?:on|at)\s+(.+?)[.!?\n]", re.I)),
]

# Statements about the speaker that are not persona-typed still belong to
# the world layer as "reported fact", but only when they name an entity.
_FACT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("event_fact", re.compile(r"\b(\w[\w' ]*?)\s+(?:is|was|has been)\s+(.+?)[.!?\n]", re.I)),
]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,;:!"))


def extract(text: str, speaker: str = "user") -> Extraction:
    result = Extraction()
    seen_persona: set[tuple[str, str]] = set()
    seen_world: set[tuple[str, str]] = set()

    for trait_type, pattern in _PERSONA_RULES:
        for match in pattern.finditer(text):
            groups = match.groups()
            if trait_type == "preference" and len(groups) == 2:
                verb, value = groups
                if re.match(r"dislike|hate|do not|don't", verb, re.I):
                    value = "dislikes " + _norm(value)
                else:
                    value = "likes " + _norm(value)
            elif trait_type == "preference" and len(groups) == 2:  # my favorite X is Y
                value = f"favorite { _norm(groups[0]) } is { _norm(groups[1]) }"
            elif trait_type == "occupation" and len(groups) == 2:
                value = f"{ _norm(groups[0]) } at { _norm(groups[1]) }"
            else:
                value = _norm(groups[-1])
            key = (trait_type, value)
            if value and key not in seen_persona:
                seen_persona.add(key)
                result.persona_candidates.append((trait_type, speaker, value))

    lowered = text.lower()
    first_person = lowered.startswith(("i ", "i'", "my "))

    for relation, pattern in _WORLD_RULES:
        for match in pattern.finditer(text):
            groups = [_norm(g) for g in match.groups()]
            subject = "user" if relation in {"affiliation", "location"} else groups[0]
            value = groups[-1]
            key = (f"{subject}|{relation}", value)
            if value and key not in seen_world:
                seen_world.add(key)
                result.world_statements.append((relation, subject, value))

    if not first_person:
        for relation, pattern in _FACT_RULES:
            for match in pattern.finditer(text):
                subject, value = _norm(match.group(1)), _norm(match.group(2))
                if len(subject) < 2 or subject.lower() in {"it", "there", "this", "that"}:
                    continue
                key = (f"{subject}|{relation}", value)
                if key not in seen_world:
                    seen_world.add(key)
                    result.world_statements.append((relation, subject, value))

    return result
