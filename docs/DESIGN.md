# landonkea-apple-products-scraper - Design & Workflow

## High-Level Overview

```mermaid
graph TB
    subgraph "Orchestration"
        A[main.py] --> B[Scrapers]
        A --> C[Price Analyzer]
        A --> D[Notifier]
        A --> E[Database]
    end

    subgraph "Scrapers"
        B --> F[eBay]
        B --> G[Swappa]
        B --> H[Apple Refurb]
        B --> I[Back Market]
        B --> J[Mercari]
        B --> K[Best Buy]
        B --> L[Gazelle]
        B --> M[Newegg]
        B --> N[Craigslist]
        B --> O[OfferUp]
        B --> P[Facebook]
    end

    subgraph "Storage"
        E --> Q[(SQLite)]
        E --> R[Price History]
    end

    subgraph "Alerts"
        D --> S[Discord Webhook]
    end
```

## Scraping Pipeline

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant M as main.py
    participant SC as Scraper
    participant PA as Price Analyzer
    participant DB as Database
    participant N as Notifier

    S->>M: Trigger scrape
    loop Each enabled site
        M->>SC: Scrape listings
        SC-->>M: Raw listings
    end
    M->>PA: Analyze prices
    PA-->>M: Scored listings
    M->>DB: Upsert listings
    M->>N: Send alerts for deals
    N-->>S: Done
```

## Price Analysis Flow

```mermaid
flowchart TD
    A[New listing] --> B{Price vs thresholds?}
    B -->|Great deal| C[High score alert]
    B -->|Good deal| D[Medium score]
    B -->|Normal| E[Log only]
    C --> F[Discord notification]
    D --> F
    E --> G[Store in DB]
    F --> G
    G --> H{Price dropped?}
    H -->|Yes| I[Price drop alert]
    H -->|No| J[Done]
```

## File Relationships

| File | Purpose | Used By |
|------|---------|---------|
| `src/main.py` | Orchestrator | Scheduler |
| `src/scrapers/` | Site-specific scrapers | `main.py` |
| `src/price_analyzer.py` | Deal scoring | `main.py` |
| `src/notifier.py` | Discord alerts | `main.py` |
| `src/database.py` | SQLite storage | `main.py` |
| `src/product_types/` | Product handlers | Scrapers |
| `config.yaml` | Configuration | All |
| `tests/` | Test suite | pytest |

## draw.io

[Open in draw.io](https://app.diagrams.net/#RApple%20scraper%20architecture)
