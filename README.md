# VAC – Vrijdag Avond Competitie

Website voor vacdenhaag.nl (Nederlands op `/`, Engels op `/en/`).

- `data/wedstrijden.csv` – reservebron als er geen Google Sheet is ingesteld
- `site/` – vaste bestanden (opmaak, lettertypen, downloads)
- `build.py` – bouwt de site naar `dist/` en rekent de stand uit
- `.github/workflows/website.yml` – bouwt en publiceert elk uur via GitHub Pages

Instelling: zet bij Settings → Secrets and variables → Actions → Variables een variabele
`SHEET_CSV_URL` met de gepubliceerde CSV-link van het tabblad Wedstrijden.

Lettertypen: Inter (SIL Open Font License) en TeX Gyre Heros/Pagella (GUST Font License), zelf gehost; zie `site/assets/fonts`.
