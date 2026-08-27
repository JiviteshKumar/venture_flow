# Sourcing decks from companies that failed — a documented negative result

**Outcome: zero usable failure decks were obtained.** The deck set therefore
remains all-winners and remains unusable for validation. This file records what
was tried, so the next session does not repeat it from scratch and does not
mistake the absence for an oversight.

## Why this was attempted

The seven-deck corpus contains only companies that succeeded — Airbnb, Uber and
Coinbase went public, Mint was acquired, Buffer, Intercom and Front still
operate. With no negative class there is no AUC, no precision and no recall; a
model returning a constant 95 scores perfectly. The set cannot validate
anything, and the fix is not "run more decks" but "obtain decks from companies
that died".

## What was tried, and what came back

**1. The aggregator already in use (media.genppt.com).** Probed 15 companies
publicly known to have failed or shut down: WeWork, Theranos, Quibi, Fast,
Juicero, Jawbone, Shyp, Munchery, Homejoy, Katerra, Beepi, Fab, Bird, Casper,
Zenefits.

**1 of 15 responded**: WeWork, at
`https://media.genppt.com/pitch-decks/wework/wework-pitch-deck-2014.pdf`
(2,930,506 bytes). It is unusable:

```
pages: 36 | text_layer: none | chars: 0
```

Thirty-six pages of slide images with no embedded text layer. This product has
no OCR path, so there is nothing to analyse. It is already recorded in
`scripts/scrape_pitch_decks.KNOWN_IMAGE_ONLY` for exactly this reason.

**2. Open web search.** Multiple queries for original decks from failed
startups. Every result was a *teardown, post-mortem or analysis* rather than a
deck: CB Insights' 483 post-mortems, postmortem.io, failory.com's cemetery,
Substack teardowns of Fast's deck, TechCrunch shutdown coverage.

That asymmetry is the finding. Post-mortems about dead startups are abundant —
thousands of them. Their **decks** are not published, because the people who
publish decks are the companies that succeeded and the aggregators that
celebrate them. Nobody re-hosts the deck of a company that lost the money.

**3. The one candidate with an actual slide URL.** "Quibi preso final" on
SlideShare. Both the page and its download endpoint return
`text/html`, 3,038 bytes — a stub, not a deck. SlideShare is also already on
this project's deck-mirror blocklist (`agents/evidence_filter`), added because
retrieving a deck's own re-hosted copy as "evidence" for its claims is circular.

## What this means, stated plainly

The bias in the deck set is **structural, not correctable by effort**. Decks
become public because companies become famous, and companies become famous by
succeeding. The survivorship filter operates on the availability of the data
itself, so no amount of searching fixes it — a different kind of source would be
needed (an investor's own archive, or a founder willing to publish a deck for a
company that died), and neither is reachable from here.

## Consequences, which are real

1. **The deck split is NOT rebalanced.** `SPLIT.lock.json` stands unchanged at
   6 train / 1 test, all successes. Re-splitting an all-positive set achieves
   nothing and would only make the lock look busier than it is.

2. **No real-deck AUC will ever be reportable from this set.** Any evaluation
   against it can only report per-company scores and check for clustering, which
   is a diagnostic, not a validation.

3. **The YC holdout remains the only population that can measure
   discrimination**, with its own stated limitation: it is a leftover with zero
   B2B and zero Fintech, so it is out-of-sample but out-of-scope.

## If this is retried

The realistic paths, in descending order of likely success:

- **Build the OCR/vision path** and unlock WeWork plus the five other known
  image-only decks (Dropbox, LinkedIn, YouTube, Facebook, BuzzFeed). WeWork
  alone would give the set its first genuine failure case. This is engineering
  work with a known target, not a search problem.
- Ask an investor or accelerator for archived decks with outcomes attached.
- Accept that deck-level validation is not available and rely on the YC
  population, stating that limitation wherever a deck-level claim is made.
