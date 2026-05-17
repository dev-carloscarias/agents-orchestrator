from abc import ABC, abstractmethod


class IngestorBase(ABC):
    @abstractmethod
    def ingest(self, source: str) -> dict:
        """Debe retornar {\"page_id\", \"page_url\", \"title\", \"raw_text\"}."""
        ...
