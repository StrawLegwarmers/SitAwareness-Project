# Notices

## This project

The code, configuration and documentation in this repository are released under the MIT licence
([LICENSE](LICENSE)).

## Content from other publishers

The daily briefs in `site/data/` and the files in `site/feeds/` contain headlines, short summaries
and links to articles published by the outlets listed in `config/*/sources.yaml`, plus data from the
public sources below. That material belongs to its publishers and is **not** covered by this
project's licence. The briefs link to each original article; read and cite the original.

The one-sentence reports in the briefs are machine-generated restatements, each attributed to its
source and checked against it automatically. They can still be wrong: verify at source before relying
on anything.

## Data sources

- **CISA Known Exploited Vulnerabilities catalog**, published by the US Cybersecurity and
  Infrastructure Security Agency.
- **Feodo Tracker** and **ThreatFox**, published by abuse.ch, used under their terms of use.
- **Google News search feeds**, used to follow outlets that have no feed of their own.
- Indicators of compromise extracted from vendors' public research reports, each linked to its report.
- **Markets data**: US Treasury daily par yield curve rates; New York Fed reference rates (SOFR,
  EFFR); ECB euro reference exchange rates and euro short-term rate; US Energy Information
  Administration spot prices; US Securities and Exchange Commission EDGAR filings and company list;
  Bureau of Labor Statistics and Bureau of Economic Analysis release calendars; TreasuryDirect auction
  announcements; central bank meeting schedules. Each is shown with its date and a link to its source.

## Third-party software

### Tabler Icons

Icon outlines in `site/assets/app.js` are taken from Tabler Icons (https://tabler.io/icons).

MIT License

Copyright (c) 2020-2024 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Python libraries

Installed at run time from `requirements.txt` (feedparser, Requests, PyYAML), each under its own
licence. They are not included in this repository.
