# Security And Data Governance

## Sensitive Data

Tender and bidder submissions may contain:

- PAN
- GSTIN
- business names and addresses
- turnover certificates
- CA certificates
- financial figures
- OEM authorization records
- commercial and procurement-sensitive information

These files should be handled as sensitive procurement data.

## GitHub Rules

Do not commit:

- `tools/.env`
- API keys
- real tender PDFs
- bidder submissions
- generated OCR outputs
- app uploads
- processing logs
- extraction matrices containing real bidder data

The `.gitignore` is configured to keep these local.

## API Egress

The turnover evaluator can use an OpenAI-compatible API through Groq. Only redacted turnover snippets should be sent, not entire bid bundles.

Before using external APIs in an official environment, confirm:

- approval from the competent authority
- data-sharing policy
- whether bidder financial data may leave the local environment
- logging and retention requirements

## Environment Variables

Create local secrets in `tools/.env`:

```env
GROQ_API_KEY=your_key_here
TURNOVER_LLM_MODEL=llama-3.3-70b-versatile
```

Commit only `tools/.env.example`.

## Human Review

The system should not make final procurement decisions. It provides:

- extracted values
- source file references
- page references
- evidence snippets
- conservative review status

Officials retain authority for final acceptance, rejection, or clarification decisions.

## Audit Trail Direction

Future versions should store append-only review logs with:

- timestamp
- tender ID
- bidder ID
- requirement ID
- extracted value
- source document/page
- system suggestion
- reviewer decision
- override reason
