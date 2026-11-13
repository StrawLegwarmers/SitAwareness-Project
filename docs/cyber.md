# Cyber

Besides its stories, the Cyber site has three collections built with plain code and no AI:
exploited vulnerabilities, indicators of compromise, and industry intelligence.

## What counts as a Cyber story

`focus`, `ignore` and `topics` in `config/cyber/site.yaml`: threat actors and campaigns, ransomware,
exploited vulnerabilities, breaches, advisories and takedowns, cyber policy, security incidents in
aviation, and major outages of cloud, IT, telecom and internet services, whatever the cause (a
global Microsoft 365 outage is a Cyber story even when Microsoft reports no malicious activity).
The two sites are independent: each reads its own feeds and makes its own stories, so the same
event can appear on both. When the AI returns nothing for a group of two or more outlets, the
audit log has a `dropped` entry for it.

## Single-source research

Most stories need two outlets. On Cyber, a major lab's or agency's own publication is news on its
own: a new campaign, threat actor or implant from Mandiant (published on Google Threat
Intelligence), Unit 42, Microsoft, CrowdStrike, Talos, OpenSourceMalware (software supply chain) and
others, or a CISA advisory. Sources listed
under `single_source_stories` in `config/cyber/site.yaml` go to the AI even when nobody else has
reported the same thing, marked "research by <outlet>", and can become a story with that one
article. Their product news never does: a headline with a word from `single_source_skip`
("introducing", "acquires", "webinar"...), or starting with the vendor's own name ("CrowdStrike
Extends..."), is left out. Such stories carry the *single source* flag until others report them.

## Exploited vulnerabilities

`pipeline/indicators.py` downloads the **CISA Known Exploited Vulnerabilities (KEV)** catalog on every
run: vulnerabilities the US agency CISA has confirmed are exploited in the wild. The **IOCs and
vulnerabilities** page shows:

- **Added to KEV** recently: vendor, product, description, CISA's remediation deadline, and a flag
  where CISA records known ransomware use.
- **CVEs in the news**: every CVE number in a cyber headline or summary, how many outlets mentioned
  it, and whether it is in KEV. A CVE that is both in the news and in KEV is the one to look at first.

These sections look back one extra day, because the brief runs in the European morning and CISA
usually updates in the US afternoon. CVE numbers link to the US National Vulnerability Database.

## Indicators of compromise

| Source | What | Key needed |
|---|---|---|
| Research reports | Indicators that vendors list in their research posts (the `intel` sources) | No |
| Feodo Tracker | Botnet command-and-control servers currently online | No |
| ThreatFox | Community indicator database, by malware family | Free key, optional (`ABUSECH_AUTH_KEY`) |

**Extraction from research reports.** Each new research post (up to 20 per run, from the last three
days) is downloaded once and scanned:

- **File hashes** (SHA-256, SHA-1, MD5) are always taken, except well-known non-indicators such as
  the hash of an empty file.
- **IP addresses, domains and URLs** are taken **only when the report defanged them**
  (`example[.]com`, `hxxp://`). Researchers defang exactly what they mean as indicators, so the
  page's ordinary links are never mistaken for them. Private and reserved IP ranges are dropped.

**Always defanged.** Indicators are stored and displayed defanged, as plain text: nothing on the
website is a working link. Each day's full list is downloadable as CSV. Real (refanged) values exist
only in the machine feeds ([feeds and OpenCTI](feeds-and-opencti.md)).

**One failure never blocks the brief.** Each source runs separately, and in the daily workflow the
whole step is allowed to fail without stopping the rest.

## Industries

The **Industry intelligence** page picks out items about specific sectors from **every** source,
geopolitical and cyber, using keyword lists in `config/cyber/industries.yaml`:

| Industry | Covers |
|---|---|
| Aviation and air transport | Airlines, airports, air traffic, airspace, aerospace manufacturers |
| Finance | Banks, payments, insurance, markets, crypto |
| Logistics and transportation | Shipping, ports, rail, road freight, postal, public transport |
| Food and beverage | Producers, drinks, supermarkets, restaurants, agriculture inputs |
| Industrial manufacturing | Factories, steel, chemicals, automotive, semiconductors, industrial control systems |
| Communication services | Telecoms, mobile operators, internet providers, cables, satellite internet |
| Energy | Oil, gas, power grids, nuclear, renewables, utilities |
| Healthcare | Hospitals, health systems, pharmaceuticals, medical devices, health insurers |
| Professional services | Consulting, audit and accounting, legal services |
| IT and software | Software makers, cloud, IT service providers, chipmakers, AI companies |

**Rules:**

- An item from a **cyber** news or research source needs a **topic** word (it's already about
  security). For broad industries (`cyber_headline: true`) the topic word must be in the headline,
  since almost every cyber article mentions software or banking somewhere.
- An item from any **other** source needs a topic word **in the headline** and a **concern** word
  (attack, outage, breach, strike, sanctions…) anywhere.
- **Exclusions** remove look-alikes before matching: "West Bank" isn't a bank, "web shell" isn't an
  energy company, "died in hospital" isn't about the health system.
- **Advisory bulletins are left out**: vendor bulletin feeds name products in every line and have
  their own page.
- Words in CAPITALS (`FAA`, `NHS`) match only in capitals; everything else ignores case.

All industries share one list of concern words (`concern:` at the top of the file) and can add their
own (`also_concern:`). An item can belong to several industries. To add a sector, copy a block: it
gets its own section and button on the page. Each section shows its newest 12 headlines, with the
rest folded, plus any stories that match.
