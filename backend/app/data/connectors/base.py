"""Abstract connector interface for disparate data sources."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional


class BaseConnector(ABC):
    """
    Abstract base class for all NEXUS data source connectors.
    
    Provides uniform lifecycle methods for opening, validating,
    and reading tabular data streams.
    """

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to data source or prepare file descriptor."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Release connection or close file descriptor."""
        pass

    @abstractmethod
    def validate_source(self) -> bool:
        """Verify that the source exists, is accessible, and has readable structure."""
        pass

    @abstractmethod
    def read_records(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Yield structured row dictionaries sequentially."""
        pass
