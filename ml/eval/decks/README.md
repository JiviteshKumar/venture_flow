# Real pitch-deck corpus

Seven genuine founder pitch decks with publicly known outcomes, used to test
whether VentureFlow's output is *true* rather than merely plausible.

The PDFs are **not committed** — see the note in `.gitignore`. `manifest.json`
records the source URL, SHA-256, byte size, extracted character count and deck
vintage for each, and re-fetching is one command:

    python scripts/scrape_pitch_decks.py --out ml/eval/decks

## Why real decks

Every deck this project was previously evaluated on was written for the
occasion. A synthetic deck tests that the pipeline executes; it cannot test
whether the pipeline is right, because whoever wrote the deck also knew what the
analyser should conclude. These were written by founders to raise real money,
and what happened next is a matter of public record.

## What is in it

| Company | Year | Chars extracted |
|---|---|---|
| Airbnb | 2009 | 2,472 |
| Uber | 2008 | 5,390 |
| Buffer | 2011 | 2,012 |
| Intercom | 2011 | 2,355 |
| Coinbase | 2012 | 635 |
| Mint | 2007 | 9,873 |
| Front | 2016 | 4,095 |

## What was rejected, and why it matters

The scraper's acceptance test was originally "does text extract from it", which
says nothing about *whose* deck it is. That produced a corpus that was 60% wrong
while every file looked correct:

- **A marketing template** quoting Uber fourteen times, kept as "Uber".
- **A how-to guide** (*How to Build the Ultimate Pitch Deck*), kept as "Buffer".
- **A blank template** opening "Hello founder!", kept as "Front".
- **A university investment club's equity pitch about Yelp stock** — names Yelp
  62 times, in the first line, and is not a template.
- **An SEO spam PDF** for Revolut whose single mention of Revolut was its title.

`looks_like_the_companys_own_deck()` now requires four things: the name appears,
it appears more than once, it appears within the opening 300 characters, and the
document is not third-party investment analysis.

This is the same failure the product itself keeps hitting — a name match
mistaken for an identity match — and it is worse here, because a corpus is meant
to be ground truth. Measurements taken against a mislabeled corpus are
meaningless *and look entirely reasonable*.

## Decks that exist but cannot be read at all

Dropbox (2007), LinkedIn (2004), YouTube (2005), Facebook (2004), WeWork and
BuzzFeed are reachable, valid, human-legible PDFs that extract to **exactly zero
characters**: every page is a slide image with no text layer. They are excluded
from the corpus and recorded in `scripts/scrape_pitch_decks.KNOWN_IMAGE_ONLY`,
because their absence is a product finding rather than a scraping failure —
see `document_extractor.text_layer` and `agents/slide_vision.py`.
