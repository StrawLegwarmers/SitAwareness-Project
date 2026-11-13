# Feeds and OpenCTI

Every run writes machine-readable files to `site/feeds/`, published with the website so other tools
can **pull** them on a schedule. Nothing needs a key, and the website never connects to anything.
Settings are in `config/feeds.yaml`. The website's **Reference → OpenCTI** page lists the live
addresses with copy buttons.

| File | Contents | In OpenCTI |
|---|---|---|
| `geo.xml`, `cyber.xml` | RSS: one item per story per day with new reporting: checked reports with source links, original headlines, region and countries | RSS Feed: one Report per item |
| `iocs.csv` | Indicators from the last 3 days, **real values**, with their source report | CSV Feed with a CSV mapper |
| `vulnerabilities.csv` | CVEs added to CISA KEV, and CVEs in the news | CSV Feed with a CSV mapper |
| `cyber-stix.json` | The same indicators and vulnerabilities as a STIX 2.1 bundle | File import, no mapper |
| `index.json` | What's in the folder and when it was built | |

**Real values.** Tools need working indicators, so these files hold them refanged, while the website
keeps showing them defanged. `site/feeds/` is never committed to Git. Full URLs are left out by
default (a refanged URL is a working link to something malicious); add `url` to `ioc_types` to include
them.

## The STIX bundle

STIX 2.1 is the standard format for sharing threat intelligence. The bundle contains:

- an **identity** (the project) and the **TLP:CLEAR** marking (TLP:WHITE in STIX 2.1 terms)
- **indicators** with detection patterns, for example `[domain-name:value = 'evil.example']`
- **malware** families named by trackers, linked by **relationships** ("indicates")
- one **report** per vendor publication, listing its indicators, with a link to it
- **vulnerabilities**, labelled when they are in CISA KEV, with links to news articles

Every object's id is derived from its content, so importing the next day's bundle updates existing
objects instead of duplicating them. The bundle passes the OASIS STIX validator.

## Connecting OpenCTI

Menu names follow current OpenCTI versions (*Integrations*); older versions have the same screens
under *Data → Ingestion*. Your OpenCTI server needs outbound HTTPS to the website.

**1. Author.** Create an organisation named **Situational Awareness Project** (*Entities →
Organizations*). Use it as the default author for every feed below, with the marking **TLP:CLEAR**.

**2. Stories (RSS).** Create an **RSS Feed** with the `cyber.xml` address (and optionally `geo.xml`),
report type `threat-report`, the author and marking above, then **Start** it. Each story becomes one
Report per day it has new reporting, titled with the story name, its description holding the
attributed sentences with source links, and an external reference back to the website.

**3. Indicators (CSV).** Download `iocs.csv` and keep its first 100 lines as a test file. Create a
**CSV mapper** (*Data → Processing → CSV Mappers*): comma separator, header on the first line. Add
representations, each with **Entity dynamic mapping**, operator *Equal*:

| Representation | When | Map column B to |
|---|---|---|
| IPv4 address | column A equals `IPv4-Addr` | Value |
| Domain name | column A equals `Domain-Name` | Value |
| File | column C equals `SHA-256` | the SHA-256 hash field |
| File | column C equals `SHA-1` | the SHA-1 hash field |
| File | column C equals `MD5` | the MD5 hash field |

Optionally map column H (report title) to Description and add an External reference from column I
(report link). Use **Test** with the sample, then create a **CSV Feed** with the `iocs.csv` address
and this mapper, every 6 hours. Field labels vary slightly between OpenCTI versions; the Test shows
what will be created.

Columns of `iocs.csv`: A `opencti_type`, B `value`, C `hash_algorithm`, D `port`, E `kind`,
F `first_seen`, G `source`, H `report_title`, I `report_url`, J `malware`.

**4. Vulnerabilities (CSV).** A mapper with one **Vulnerability** representation (Name from column A,
Description from column F, optionally an External reference from column K), and a CSV Feed with the
`vulnerabilities.csv` address.

Columns: A `cve`, B `why_listed`, C `vendor`, D `product`, E `name`, F `description`,
G `kev_date_added`, H `kev_due_date`, I `known_ransomware_use`, J `outlets_in_news`, K `example_article`.

**5. STIX bundle.** Download `cyber-stix.json` and upload it under *Data → Import*. No mapper is
needed.

**6. Check.** Within an hour: *Integrations → Deployed* shows the feeds running; *Analyses → Reports*
filtered by the author shows stories; *Observations* shows indicators; *Arsenal → Vulnerabilities*
shows CVEs. If a feed fails, open its address in a browser from the OpenCTI network: a failure there
points to a proxy or firewall rule.

## Good to know

- The files are rebuilt every 3 hours. Polling every hour or two is plenty.
- Re-ingesting is safe: observables merge by value, vulnerabilities by CVE number, RSS items have
  stable ids.
- Stories are collection, not assessment: verify at source before relying on them.
- Indicators come from published reports and trackers and are not reviewed. Consider importing them
  as observables with a moderate confidence, and promoting to indicators after review.
- Everything ingested carries the project as author, so it can be filtered or removed as a set.
