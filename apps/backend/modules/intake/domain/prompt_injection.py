"""MOD-005: advisory prompt-injection heuristics for intake AI egress (#780).

The intake pipeline calls :func:`detect_prompt_injection` on the transcript
immediately before the structuring provider is asked to read it. The check is
advisory: a finding is recorded for security monitoring and the pipeline
continues. Nothing here changes the transcript, rejects an intake, or blocks
egress.

The result is deliberately small. It names the categories that matched and a
bounded score. It never carries the input text, a matched substring, an offset,
or any patient content - that is the contract the observability consumer relies
on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, TypeAlias

#: The closed category vocabulary the probe can report.
PromptInjectionCategory: TypeAlias = Literal[
    "instruction_override",
    "system_prompt_probing",
    "exfiltration",
    "tool_call",
]

INSTRUCTION_OVERRIDE: PromptInjectionCategory = "instruction_override"
SYSTEM_PROMPT_PROBING: PromptInjectionCategory = "system_prompt_probing"
EXFILTRATION: PromptInjectionCategory = "exfiltration"
TOOL_CALL: PromptInjectionCategory = "tool_call"

#: The closed category vocabulary, in the stable order findings report them.
PROMPT_INJECTION_CATEGORIES: tuple[PromptInjectionCategory, ...] = (
    INSTRUCTION_OVERRIDE,
    SYSTEM_PROMPT_PROBING,
    EXFILTRATION,
    TOOL_CALL,
)

#: The score is capped so a pathological input cannot emit an unbounded number.
MAX_SCORE = 100

#: Each additional distinct pattern a category hits adds this much to its weight.
_EXTRA_PATTERN_WEIGHT = 5


@dataclass(frozen=True)
class PromptInjectionFinding:
    """What the advisory screen found: category names and a bounded score.

    An empty ``categories`` tuple means nothing matched. The type deliberately
    has no text field, so a caller cannot accidentally forward the screened
    content along with the finding.
    """

    categories: tuple[PromptInjectionCategory, ...]
    score: int

    @property
    def detected(self) -> bool:
        """True when at least one category matched."""
        return bool(self.categories)


@dataclass(frozen=True)
class _CategoryRule:
    """One category's base weight and the patterns that trigger it."""

    category: PromptInjectionCategory
    weight: int
    patterns: tuple[re.Pattern[str], ...]

    def hit_count(self, text: str) -> int:
        """How many distinct patterns for this category matched ``text``."""
        return sum(1 for pattern in self.patterns if pattern.search(text))


_RULES: tuple[_CategoryRule, ...] = (
    _CategoryRule(
        category=INSTRUCTION_OVERRIDE,
        weight=40,
        patterns=(
            re.compile(
                r"\bignore\s+(?:all\s+|any\s+|the\s+)?"
                r"(?:previous|prior|above|earlier|preceding)\b"
            ),
            re.compile(
                r"\bdisregard\s+(?:all\s+|any\s+|the\s+)?"
                r"(?:previous|prior|above|earlier|system|instruction|rule)"
            ),
            re.compile(
                r"\bforget\s+(?:all\s+|any\s+|the\s+)?"
                r"(?:previous|prior|above|earlier)\b"
            ),
            re.compile(
                r"\boverride\s+(?:the\s+|your\s+)?"
                r"(?:instruction|system|prompt|rule|guardrail)"
            ),
            re.compile(r"\byou\s+are\s+now\b"),
            re.compile(r"\bnew\s+(?:instructions|rules|system\s+prompt)\b"),
            re.compile(r"\bdo\s+not\s+follow\s+(?:the\s+|your\s+)?(?:instruction|rule)"),
            re.compile(
                r"\bact\s+as\s+(?:an?\s+)?"
                r"(?:different|new|unrestricted|jailbroken|unfiltered)\b"
            ),
            re.compile(r"\bjailbreak\b"),
        ),
    ),
    _CategoryRule(
        category=SYSTEM_PROMPT_PROBING,
        weight=30,
        patterns=(
            re.compile(r"\bsystem\s+prompt\b"),
            re.compile(
                r"\b(?:reveal|show|print|repeat|display|output|tell\s+me)\s+"
                r"(?:me\s+)?(?:your\s+|the\s+)?(?:system\s+)?"
                r"(?:prompt|instructions|rules|guidelines)\b"
            ),
            re.compile(
                r"\bwhat\s+(?:is|are)\s+your\s+(?:system\s+prompt|"
                r"system\s+instructions|initial\s+instructions|"
                r"original\s+instructions|hidden\s+instructions)\b"
            ),
            re.compile(r"\bhidden\s+(?:prompt|instructions|rules)\b"),
            re.compile(r"\bdeveloper\s+(?:prompt|message|instructions)\b"),
            re.compile(r"\byour\s+(?:initial|original|system)\s+instructions\b"),
        ),
    ),
    _CategoryRule(
        category=EXFILTRATION,
        weight=50,
        patterns=(
            re.compile(
                r"\b(?:send|email|post|upload|transmit|forward|exfiltrate|leak|dump)\b"
                r"[^\n]{0,60}\b(?:to|http|https|ftp|@|external|outside)\b"
            ),
            re.compile(r"\b(?:exfiltrate|leak|steal)\b"),
            re.compile(
                r"\b(?:reveal|show|give|tell|print|leak|dump|expose|list|send)\b"
                r"[^\n]{0,40}\b(?:api[\s_-]?key|secret|password|credential|"
                r"access\s+token|private\s+key)\b"
            ),
            re.compile(
                r"\b(?:what(?:'s| is)|tell\s+me)\s+(?:the\s+)?(?:admin\s+)?"
                r"(?:password|api\s+key|secret)\b"
            ),
            re.compile(
                r"\b(?:dump|reveal|show|list|export)\b[^\n]{0,40}"
                r"\b(?:patient|user)\s+(?:data|records?|information)\b"
            ),
            re.compile(r"\b(?:all|every)\s+(?:patient|user)\s+(?:data|records?)\b"),
            re.compile(r"\bbase64\b"),
            re.compile(r"https?://"),
            re.compile(r"\bcurl\s"),
            re.compile(r"\bwebhook\b"),
            re.compile(r"\b(?:database|db)\s+(?:dump|credentials?)\b"),
        ),
    ),
    _CategoryRule(
        category=TOOL_CALL,
        weight=35,
        patterns=(
            re.compile(r"\btool[\s_-]?calls?\b"),
            re.compile(r"\bfunction[\s_-]?calls?\b"),
            re.compile(
                r"\b(?:call|invoke|execute|run)\s+(?:the\s+|a\s+|your\s+)?"
                r"(?:tool|function|command|script|shell|api|endpoint)\b"
            ),
            re.compile(r"\buse\s+(?:the\s+|a\s+|your\s+)?(?:tool|function|api)\b"),
            re.compile(r"\b(?:bash|powershell|cmd\.exe)\b"),
            re.compile(r"\bpython\s+(?:script|code|-c)\b"),
            re.compile(r"\bnode\.js\b"),
            re.compile(r"<tool"),
            re.compile(r"<function"),
            re.compile(r"```"),
            re.compile(r"\{\s*\"(?:tool|function|name)\"\s*:"),
            re.compile(r"\bapi\s+call\b"),
        ),
    ),
)


def _normalize(text: str) -> str:
    """Fold width and case, then collapse whitespace to single spaces."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(folded.split())


def detect_prompt_injection(text: str) -> PromptInjectionFinding:
    """Screen ``text`` for the four prompt-injection categories.

    Pure and deterministic: the same text always yields the same categories and
    score. Returns an empty finding for blank input or ordinary clinical text.
    """
    haystack = _normalize(text)
    if not haystack:
        return PromptInjectionFinding(categories=(), score=0)

    matched: list[PromptInjectionCategory] = []
    score = 0
    for rule in _RULES:
        hits = rule.hit_count(haystack)
        if hits == 0:
            continue
        matched.append(rule.category)
        score += rule.weight + (hits - 1) * _EXTRA_PATTERN_WEIGHT

    return PromptInjectionFinding(categories=tuple(matched), score=min(score, MAX_SCORE))
