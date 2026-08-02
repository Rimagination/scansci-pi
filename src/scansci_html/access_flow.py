from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccessState(str, Enum):
    UNKNOWN = "unknown"
    ARTICLE_PAGE = "article_page"
    ACCESS_ENTRY = "access_entry"
    INSTITUTION_PICKER = "institution_picker"
    HUMAN_LOGIN = "human_login"
    FULLTEXT = "fulltext"
    SUBSCRIPTION_PREVIEW = "subscription_preview"
    SECURITY_CHALLENGE = "security_challenge"


@dataclass(frozen=True)
class AccessEvidence:
    state: AccessState
    url: str
    markers: tuple[str, ...] = ()


class AccessStateMachine:
    def __init__(self, recipe: object) -> None:
        self.recipe = recipe

    def inspect(self, page: object) -> AccessEvidence:
        return self.recipe.inspect(page)
