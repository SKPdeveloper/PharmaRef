# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PharmaRef is a Ukrainian drug reference web application. It provides pharmaceutical information with legal status tracking, combining Ukrainian State Register (DRLZ) data with US OpenFDA API.

**Status**: Greenfield project. Only specification exists (`pharmaref_specification_v2.md`), no implementation yet.

## Architecture

```
pharmaref/
├── app.py                 # Flask entry point
├── config.py
├── data/                  # Static normative JSON files
│   ├── controlled_ua.json     # KMU No.770/2000 Tables I-III
│   ├── controlled_dea.json    # DEA Schedules I-V
│   └── atc_codes.json         # ATC classifier
├── services/
│   ├── db.py              # SQLite + FTS5, get_db(), init_db()
│   ├── drlz_loader.py     # DRLZ CSV parsing (windows-1251 encoding)
│   ├── fda_client.py      # OpenFDA HTTP client with 24h cache
│   ├── search_service.py  # Three search modes
│   ├── status_resolver.py # Legal status determination
│   └── analog_finder.py   # Analog discovery via INN & ATC
├── routes/
│   ├── search.py          # GET /search
│   └── api.py             # REST API endpoints
├── templates/             # Jinja2
└── static/                # CSS + vanilla JS
```

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite with FTS5 virtual table
- **External APIs**: OpenFDA Drug Label API, DRLZ CSV feed
- **Frontend**: Jinja2 templates, vanilla JavaScript (no jQuery)

## Core Features

Three search modes:
1. **F-01**: By drug name (trade name + INN) - FTS5 search
2. **F-02**: By disease/indication - FTS5 + ATC code lookup via static dictionary (80 ICD-10 conditions)
3. **F-03**: By active ingredient - finds analogs by INN matching

Legal status resolution priority:
- Forbidden in Ukraine (KMU No.770 Table I)
- Restricted circulation (Table II)
- Precursor (Table III)
- DEA Schedule (US-only drugs)
- Conflicting UA/DEA status
- Prescription-only (from DRLZ `dispensing_condition`)
- OTC

## Data Sources

**DRLZ CSV** (`drlz.com.ua`):
- Encoding: windows-1251
- Delimiter: semicolon
- Fields used: trade_name, inn, atc_code, dispensing_condition, reg_number, status
- No indications data available

**OpenFDA**:
- Real-time queries with 24-hour cache
- Only 5 fields extracted: brand_name, generic_name, substance_name, indications_and_usage, purpose
- Rate limit: 240 req/min without API key

## Database Schema

Core table `drugs` unifies UA and FDA records with `source` field ('ua'|'fda').
FTS5 virtual table `drugs_fts` indexes trade_name, inn, indications.
Separate tables for `controlled_ua`, `controlled_dea`, `atc`.

## API Endpoints

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/search?q=&mode=name\|disease\|ingredient` | Main search |
| GET | `/api/analogs?inn=` | Find analogs by INN |
| GET | `/api/status?substance=` | Get legal status |
| GET | `/api/db/info` | DRLZ update date, record count |

## Key Constraints

- Indications exist only for FDA drugs (DRLZ CSV lacks them)
- UA drugs get indications via ATC code reference only
- Normative lists (controlled substances) require manual updates
- No pagination - single-page results with client-side filtering
