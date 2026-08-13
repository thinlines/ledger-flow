# Keep a first-party application over an API-only product

Ledger Flow remains a first-party application for understanding and maintaining
personal finances rather than becoming an API-only product. Its API is the
shared accounting foundation for the application, scripts, and agents, but the
human workflows and interactive analytical experience are part of the product
rather than a disposable client. This preserves the desired Power BI-like
cross-filtering and drill-through experience while allowing every client to use
the same trustworthy accounting behavior.

## Considered Options

- **API-only product** — rejected because it abandons the human judgment
  workflows and analytical experience instead of repairing them.
- **UI-specific accounting behavior** — rejected because different clients could
  produce or explain different books.

## Consequences

The frontend may be substantially redesigned, but it is not removed merely to
reduce current UX friction. Accounting operations and analytical definitions
must be exposed through the shared API rather than recreated independently in
the application.
