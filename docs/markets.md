# Markets

The Markets section collects what news outlets and official bodies publish about markets,
companies and the economy, for traders and analysts. It follows the same rules as the rest of the
tool: code groups the headlines, the AI only restates single reported facts with their source, code
checks every sentence, and numbers in tables come from official data read by code. **Nothing here is
investment advice**: no ratings, price targets, forecasts, scores or recommendations, and the website
says so at the top of the brief.

## Pages

| Page | Shows | Made by |
|---|---|---|
| Brief | Bottom line up front, most reported stories, every story, and "From the Geopolitical brief": today's Geopolitical stories about oil, sanctions, tariffs and other market topics (`geo_links` in `site.yaml`), linked to their page | Code groups, the AI restates, code checks |
| Rates and calendar | Official rates and prices, and the next 7 days | Code only (`pipeline/markets_data.py`) |
| Central banks and releases | Fed, ECB, Bank of England, Bank of Japan, SNB, Bank of Canada, RBA, BIS, BEA, Census, EIA, WTO, SEC and CFTC releases | Plain list from their feeds |
| Company filings | SEC 8-K filings by US-listed companies in the last day, by type | Code only |
| Analysis | Analysis from outlets (FT Lex and Alphaville, The Economist, Liberty Street Economics, FEDS Notes, ECB Blog), labelled | Listed, never restated |
| Markets headlines | Every news headline of the last two days | Plain list |

The Cyber site's "IOCs and vulnerabilities" page also lists **material cybersecurity incidents
disclosed to the SEC** (8-K Item 1.05) from the same filings data.

## Sources

`config/markets/sources.yaml`, in three sections: `news` (grouped into stories), `official` (a plain
list) and `analysis` (listed and labelled, `kind: analysis`). Paywalled outlets (FT, WSJ, Bloomberg,
The Economist) are used only through the headline and short summary their public feeds carry, with a
link back; article pages are never fetched. Left out on purpose: Yahoo Finance (its feed terms forbid
modified display), Seeking Alpha (its terms forbid automated reproduction) and stock index levels
such as the S&P 500 or the Dow (licensed data).

Stories need two outlets, like Geopolitical stories, and the AI labels each with a topic; the
Markets site keeps company and market news (`topics` in `site.yaml`). It uses at most 3 AI calls a
run (`ai: {max_calls: 3}` in `site.yaml`), because market news concentrates in fewer, bigger stories.

## Rates and prices

| Rows | Source | Notes |
|---|---|---|
| 3-month, 2-, 10- and 30-year Treasury par yields | US Treasury, daily yield curve | Public domain |
| SOFR, effective fed funds rate | New York Fed reference rates API | Published the next business day |
| Euro short-term rate (€STR) | ECB data API | |
| EUR/USD, GBP, JPY, CHF, CNY | ECB euro reference rates | Set around 14:15 CET; reference rates, not market closes |
| WTI, Brent, Henry Hub spot | EIA daily spot price files | Public domain; usually a day or two behind |

Each row shows the latest value its source has published, the date it applies to, the change from
the source's previous value (basis points for rates), and a link to the source. **Fail closed**: a
value that couldn't be fetched, or that falls outside a sensible range (a 10-year yield of 512%), is
shown as "not available" with the reason, never as zero or as an older number. A value more than 7
days old is flagged *stale*.

## The next 7 days

- **Central bank decisions** (Fed, ECB, Bank of England, Bank of Japan) from
  `config/markets/calendar.yaml`, copied from each bank's published schedule with a link. The
  banks publish the next year's dates during the year: add them when they do. The website says how
  far ahead the file goes.
- **US statistical releases** from the BEA and BLS calendars (iCalendar files), in Eastern time.
- **US Treasury auctions** from TreasuryDirect, with the amount offered.

No forecasts or "consensus" numbers: those are licensed, and they are predictions.

## Company filings (SEC EDGAR)

The 8-K is the report a US-listed company must file within four business days of a material event.
`markets_data.py` reads EDGAR's list of the latest 8-Ks (up to 1,200 a run, stopping at filings more
than a day old), keeps companies with a stock ticker (from the SEC's company list), and groups them
by item, most unusual first:

| Item | Shown as |
|---|---|
| 1.05 | Cybersecurity incidents (also on the Cyber site) |
| 1.03 | Bankruptcy or receivership |
| 3.01 | Delisting notices and listing rule failures |
| 4.02 | Earlier financial statements no longer reliable |
| 5.01 | Changes in control |
| 2.01 | Acquisitions and sales completed |
| 1.01, 1.02 | Material agreements signed, ended |
| 2.05, 2.06 | Exit or restructuring costs, impairments |
| 4.01 | Auditor changes |
| 5.02 | Directors and officers: departures and appointments |
| 2.02 | Results of operations |

Only the filing's type is shown, with a link: the website never says what a filing means.

### The contact email (SEC_CONTACT_EMAIL)

The SEC asks every automated request to say who is asking, with an email address, and limits
requests to 10 a second (this uses fewer than 15 a day, spaced out). BLS refuses requests without
one. Add it as a repository secret: Settings → Secrets and variables → Actions → New repository
secret, name `SEC_CONTACT_EMAIL`. It is passed only to the market data step, only ever sent to
sec.gov and bls.gov in the request header, and never written to the repository, the website or the
logs (the tests check this). Without it, filings and the BLS calendar are skipped and the website
says so.

## Running it locally

```bash
python pipeline/fetch.py --site markets
SEC_CONTACT_EMAIL=you@example.org python pipeline/markets_data.py --show   # or without, to skip filings
AI_PROVIDER=mock python pipeline/narratives.py --site markets
python pipeline/export.py
```
