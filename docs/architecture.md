# Architecture

## High-level components
- Frontend Web App
- Backend API (FastAPI)
- EPAM AI DIAL (LLM calls)

## Mermaid Sequence Diagram
```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant FE as Frontend UI
    participant BE as Backend API
    participant D as EPAM AI DIAL

    U->>FE: Add action items + transcript
    FE->>BE: POST /analyze
    BE->>D: Chat completion (mapping/classification/suggestions)
    D-->>BE: Structured analysis JSON
    BE-->>FE: mapped/unmapped/suggestions
    FE-->>U: Render results + filters

    U->>FE: Map unmapped feedback manually
    FE->>BE: POST /mappings/manual (planned)
    BE-->>FE: Updated mappings

    U->>FE: Generate MOM
    FE->>BE: POST /mom
    BE->>D: Chat completion (MOM generation)
    D-->>BE: MOM text
    BE-->>FE: MOM content
```

## API scope in this starter
- `GET /health`
- `POST /analyze`
- `POST /mom`

## Next scope
- Persistent storage for action items and mappings
- Manual mapping endpoint
- Authentication and role controls
- End-to-end tests and prompt quality evaluation
