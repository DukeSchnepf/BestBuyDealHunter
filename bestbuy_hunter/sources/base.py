"""Common interface every retailer source implements."""
from __future__ import annotations

import abc

from ..config import Config
from ..models import Deal


class Source(abc.ABC):
    """A retailer adapter that yields normalized candidate deals."""

    #: short, stable identifier (also used as Deal.retailer), e.g. "bestbuy".
    name: str = "source"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def scan(self) -> list[Deal]:
        """Run this retailer's queries and return raw (un-curated) candidates.

        Implementations should never raise on a single failed query — log and
        return whatever was gathered so one flaky retailer can't sink a cycle.
        """
        raise NotImplementedError
