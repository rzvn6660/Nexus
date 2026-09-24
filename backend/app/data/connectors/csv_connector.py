"""CSV Connector implementing BaseConnector for file and stream reading."""

import csv
import io
import os
from typing import Any, Dict, Generator, List, Optional, Union
from app.data.connectors.base import BaseConnector


class CSVConnector(BaseConnector):
    """
    Reads delimited text/CSV records from local filesystem paths,
    strings, or IO byte/text streams.
    """

    def __init__(
        self,
        source: Union[str, io.StringIO, io.BytesIO],
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> None:
        self.source = source
        self.delimiter = delimiter
        self.encoding = encoding
        self._reader: Optional[csv.DictReader] = None
        self._file_handle: Optional[io.TextIOBase] = None
        self._headers: Optional[List[str]] = None

    def connect(self) -> None:
        """Open file descriptor or stream for reading."""
        if isinstance(self.source, str):
            if os.path.exists(self.source):
                self._file_handle = open(self.source, mode="r", encoding=self.encoding, errors="replace")
            else:
                # Treat raw text string as CSV content
                self._file_handle = io.StringIO(self.source)
        elif isinstance(self.source, io.BytesIO):
            self._file_handle = io.TextIOWrapper(self.source, encoding=self.encoding, errors="replace")
        elif isinstance(self.source, io.StringIO):
            self._file_handle = self.source
        else:
            raise ValueError(f"Unsupported CSV source type: {type(self.source)}")

        self._reader = csv.DictReader(self._file_handle, delimiter=self.delimiter)
        self._headers = [h.strip() for h in (self._reader.fieldnames or []) if h]

    def disconnect(self) -> None:
        """Safely close open file descriptors."""
        if self._file_handle and not isinstance(self.source, (io.StringIO, io.BytesIO)):
            self._file_handle.close()
        self._reader = None
        self._file_handle = None

    def validate_source(self) -> bool:
        """Validate header presence and readability."""
        if not self._reader:
            self.connect()
        return bool(self._headers and len(self._headers) > 0)

    @property
    def headers(self) -> List[str]:
        """Return discovered CSV column headers."""
        if not self._reader:
            self.connect()
        return self._headers or []

    def read_records(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        """Yield parsed row dictionaries sequentially."""
        if not self._reader:
            self.connect()

        count = 0
        assert self._reader is not None
        for row in self._reader:
            # Strip whitespace from keys and values
            cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            yield cleaned
            count += 1
            if limit and count >= limit:
                break
