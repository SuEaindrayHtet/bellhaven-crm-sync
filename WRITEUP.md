# Writeup

Time spent: 45 min (fill in honestly)

AI use: built with Claude. I directed the design, checked the proposals against
the CRM browser and the website by hand, and made the judgment calls below.

## Approach

1. Scrape all locations (35: 34 in the directory plus one linked only from the home page).
2. Read all CRM accounts (121).
3. Match each location to CRM accounts, searching the whole CRM, not just Bellhaven's children.
4. Turn each difference into a proposal with evidence. Nothing is written.
5. A reviewer approves or rejects in the app. Approved items are written through the API after a freshness check.

## Matching rules, strongest first

1. Same normalized street and zip.
2. Same normalized street and city/state (catches a mistyped zip).
3. Same house number, street text at least 85% similar, same city or zip.
4. Name at least 90% similar AND same city or zip (catches a PO Box billing address).

A name match alone never links accounts. That is deliberate: the CRM has an
"Amberly Manor" in Colorado, a "Union Square Senior Living" at a different New
Albany address under another operator, and "Bellhaven of New Carlisle" (OH) next
to the website's "Bellhaven of Carlisle" (PA). These are shown to the reviewer
as near misses on the create proposal, not matched.

## What the run found (27 proposals)

| Kind | Count | Examples |
|---|---|---|
| CHOW, new account | 2 | Tiffin, Marietta: under Cedar Trail with revenue and open AR |
| CHOW, link only | 1 | Sandusky: sold to Millstone, whose account already exists |
| Fix existing account | 11 | Lima and Findlay re-parented; Zanesville and Kettering re-parented and renamed; Portsmouth zip; five renames |
| Duplicate | 7 | Port Clinton, Erie, Monroe x2, Kettering x2, Owosso |
| New account | 4 | Batavia, Union Square, Carlisle PA, Amberly Manor (Hudson OH) |
| Needs Review | 2 | Alliance, Coldwater |

The other 18 locations matched with nothing to change.

## The billing SOP

`sop.must_preserve(account)` is true only when lifetime revenue > 0 AND
outstanding AR > 0. If such an account sits under the wrong parent, it is never
edited apart from `chow_current_account`. Otherwise it is re-parented directly
(Lima has revenue but no AR, so it moves). The check runs when the proposal is
built and again just before the write.

## Judgment calls

- **Sandusky.** Not on the website; a Millstone account exists at the same
  address. It has revenue and open AR, so I did not re-parent it. I also did
  not create a second new account: I set `chow_current_account` to the existing
  Millstone account. Creating another would have added a duplicate.
- **Duplicate survivor.** Order: already under Bellhaven, has billing history,
  phone equals the website's, match strength, has a parent, Active, name
  similarity, lowest id. For Kettering none of the three copies was under
  Bellhaven or had billing, so the choice (the Harborview copy) is the weakest
  call here; the other two point at it.
- **Alliance and Coldwater.** Under Bellhaven, not on the website, no other
  account at their address. I flagged them Needs Review with a note instead of
  guessing a new parent or removing the parent.
- **Ashtabula.** The CRM billing address is a PO Box. Name, city, zip and phone
  all match, so it is linked, but I left the PO Box alone because a billing
  address can legitimately differ from the physical one.
- **Small name differences.** Case, punctuation, "&" vs "and" and a leading
  "The" are ignored ("Arbors at Bellhaven Dayton" is left as is). Real wording
  changes ("Rehab and Nursing" to "Rehabilitation & Nursing") are proposed.
- **Phone.** Used as matching evidence only. I do not propose phone changes
  because the brief lists name, address and care offerings.
- **Care type.** Website labels map to the CRM vocabulary (Memory Support ->
  Memory Care, Short-Term Rehabilitation & Nursing -> Skilled Nursing). A
  location with two offerings is fine if the CRM holds either one.
- **34 vs 35.** The home page says 35 communities; the directory lists 34.
  Findlay is only linked from the home page, so the scraper follows those links.

## Re-run safety

- Proposal key = hash of (type, account, location, proposed values). Inserting
  an existing key is ignored, so approved and rejected items never come back.
- If the website or CRM changes so the proposed values differ, the key differs
  and a new proposal appears.
- Accounts already marked duplicate or CHOW are skipped on later runs.
- Pending proposals that a later run no longer produces are marked stale.
- A second run on the corrected CRM produces zero proposals (covered by a test).

## Write safety

- The pipeline has no code path that writes to the CRM.
- Before a write the account is fetched again; if any watched field changed
  since the proposal, the write is refused and the item marked stale.
- CHOW saves the new account id before touching the old account, and checks for
  an existing account at that address, so a retry cannot create a second one.
- If a scrape returns under 70% of the previous count the run stops, so a
  broken page cannot flag live accounts as removed.

## Limits and next steps

- Proposal state is a local SQLite file; with several reviewers it should be a shared database.
- No record of who approved what; add reviewer identity.
- Street normalization is a word list, not a full address parser.
- Needs Review items still need a person to find the new owner.
