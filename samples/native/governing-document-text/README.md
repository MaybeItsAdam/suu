# native/governing-document-text — extracted governing-document text (real excerpts)

- **Shape**: the `formattedText` stored per governing document — a `# Title` /
  `Source:` / `Version:` header, then one paragraph or clause per line, `##`/`###`
  headings, sub-clauses indented two spaces per level, Markdown tables.
- **Produced by**: `suu`'s layout-aware extractor (`src/suu/scrape/gov_text.py`,
  `extract_structured_text`), run by `ucl-suu-pipeline`'s `gov-collect` task, which adds
  the header and writes the text to the Toolbox database.
- **Files**: excerpts of the Bye-Laws (main + Appendix 2), Code of Practice, Memorandum
  and Articles, Clubs and Societies Regulations; `legacy-byelaws-main.txt` is a slice of
  the older pypdf text prod held before the re-collect (kept so the parser still reads
  it).
- **Real or synthetic**: real extractor output, cut to excerpts.
- **Captured**: 2026-09-25 (from the July 2026 documents).
- **Redacted**: no — public documents.
- **Read by**: the Toolbox's `src/lib/governingDocumentText.test.ts` through its copy in
  `src/lib/__fixtures__/governing-documents/` — sync with `node scripts/sync-samples.mjs`
  there; `src/lib/samplesDrift.test.ts` fails on drift.
