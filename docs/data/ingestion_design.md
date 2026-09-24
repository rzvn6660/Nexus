# NEXUS Data Ingestion Architecture & Design

## 1. Design Overview
The NEXUS Ingestion Engine is engineered around a contract-first philosophy:
- Incoming tabular data must conform to predefined entity contracts before touching database tables.
- Ingestion is stateless and sandboxed: no arbitrary Python expressions, regex injections, or shell invocations can be triggered via file payloads.

---

## 2. Ingestion Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client as Data Operator / API Client
    participant API as /api/v1/data/ingest/csv
    participant Connector as CSVConnector
    participant Service as CSVIngestionService
    participant Contract as Pydantic Domain Contract
    participant DB as PostgreSQL Session

    Client->>API: POST /ingest/csv (dataset='products', file=products.csv, persist=true)
    API->>Service: ingest_csv(dataset, stream, filename, persist)
    Service->>Connector: connect() & read header row
    Connector-->>Service: headers list
    Service->>Service: Validate required header columns
    
    alt Missing Required Columns
        Service-->>API: IngestionResult(success=false, error=MISSING_COLUMNS)
        API-->>Client: 200 OK (IngestionResult with error report)
    else Headers Valid
        loop For each row in CSV
            Connector->>Service: Yield clean raw row
            Service->>Contract: Validate row data types & constraints
            alt Row Valid
                Service->>Service: Stage valid ORM object
            else Row Malformed
                Service->>Service: Record IngestionRowError(row_num, col, reason)
            end
        end
        
        alt Zero Errors and persist=true
            Service->>DB: Bulk insert mapped objects
            DB-->>Service: Commit confirmed
        end
        
        Service-->>API: IngestionResult(rows_read, rows_valid, rows_failed, errors)
        API-->>Client: 200 OK (IngestionResult)
    end
```

---

## 3. Extensible Connector Interface (`BaseConnector`)
All current and future connectors implement the standard lifecycle interface:

```python
class BaseConnector(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def validate_source(self) -> bool: ...
    @abstractmethod
    def read_records(self, limit: Optional[int] = None) -> Generator[Dict[str, Any], None, None]: ...
```

This guarantees that future connectors for PostgreSQL foreign tables, Amazon S3 Parquet, Snowflake, and Shopify REST APIs can be added as drop-in plugins without altering the ingestion service or validation logic.
