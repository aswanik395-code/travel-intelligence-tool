# Travel Intelligence Tool

Enter a country, get its capital, currency, population, languages, region and neighbours,
using the REST Countries API (v5): https://restcountries.com

## Setup
1. Install: `pip install -r requirements.txt`
2. Get a free API key: https://restcountries.com/sign-up
3. Copy `.env.example` to `.env` and paste your key:
       COUNTRY_API_KEY=your_api_key_here

## Run
    python travel_tool.py Japan
    python travel_tool.py "South Africa" --save   # also writes sample_outputs/south_africa.txt
    python travel_tool.py Japan --raw             # also prints the raw API record

## Generate sample outputs (4 countries plus invalid inputs)
    python run_samples.py

## Test (offline, API mocked, no key needed)
    python -m unittest -v

## Configuration
`config.json` holds the base URL, key variable name, timeout and requested fields.
Override the URL with the `COUNTRY_API_BASE_URL` environment variable.

## Files
- travel_tool.py: main tool
- config.json: external configuration
- .env.example: template for your API key (never commit the real .env)
- run_samples.py: runs several countries and saves outputs
- test_travel_tool.py: offline unit tests
- sample_outputs/: saved results
- OBSTACLE_LOG.md: issues and solutions