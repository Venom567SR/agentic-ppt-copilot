"""scripts/smoke_retrieval.py -- smoke test: extract -> corpus map -> curate."""
from ai.agents.context_retriever import build_corpus, curate

# <= 3 files (the cap). This subset covers CSV + Excel + prose PDF.
PATHS = [
    r"C:\Users\sahil\Downloads\nr\output_files_npa_trends.csv",
    r"C:\Users\sahil\Downloads\nr\output_files_bank_financials.xlsx",
    r"C:\Users\sahil\Downloads\nr\output_files_rbi_overview.pdf",
]

AGENDA = """Indian Banking Sector: Growth & Outlook.
Slides: (1) Sector at a glance, (2) Asset quality & NPA trends,
(3) Profitability & capital adequacy, (4) 5-year outlook."""

def main():
    corpus = build_corpus(PATHS)            # extract + dedup + cap
    print("\n===== CORPUS MAP =====")
    print(corpus.map_for_planner(max_chars=4000))

    mem = curate(corpus, AGENDA)            # LLM curation -> temporary memory
    print(f"\n===== CURATED: {len(mem.chunks)}/{len(corpus.chunks)} chunks kept =====")
    print("sources:", [s.title for s in mem.sources()])
    print("\n----- evidence preview (first 800 chars) -----")
    print(mem.as_evidence()[:800])

    mem.discard()                           # temporary memory cleared after use
    print("\nafter discard -> empty:", not mem)

if __name__ == "__main__":
    main()