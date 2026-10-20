# Fishcast

A fishing forecast that gives tips for each spot, species and set of conditions, and learns from your own catch log.

It's one self-contained page, `index.html`, with no build step.

## What it does
- **Spots**: save a location, water type, usual clarity, the structure there (points, docks, grass, oyster bars, inlets…) and the species you target.
- **Live conditions** (from [Open-Meteo](https://open-meteo.com), no API key needed): air temperature, wind, gusts, pressure and its 3-hour trend, cloud cover, rain, cold-front detection and, for saltwater spots, sea-surface temperature and waves. The page computes sun and moon positions itself (sunrise and sunset, moon phase, and solunar major and minor periods).
- **Bite score**: hourly for the next 48 hours, with the factors behind it (for example "+12 falling pressure" or "−10 post-front") and the three best 2-hour windows.
- **Game plan**: seasonal pattern by water temperature for 14 species (where the fish are, what to throw, how to fish it), plus tips for the current conditions (pressure, wind direction and which bank to fish, sky, rain, clarity, light, solunar, tide) and tips for each kind of structure at the spot.
- **Catch log**: every catch, and every trip with no bites, saves a snapshot of the conditions. The Today tab shows what you've caught at this spot in similar conditions, and the log shows your patterns by lure, time of day, pressure, sky, water temperature and tide.

## Run it
Open `index.html` in a browser, or serve the folder (`python -m http.server -d fishcast`).
To use it on your phone, enable GitHub Pages (Settings → Pages → Source: GitHub Actions) and run the `fishcast-pages` workflow. Then add the page to your home screen.

Spots and catches are stored in the browser's localStorage. Inside a Claude artifact they're stored in your private artifact data instead.

## Accuracy notes
- Freshwater temperature is **estimated** from the last 4–7 days of air temperature and can be off by 5 °F or more. A thermometer reading entered on the Today tab overrides it for 3 days, and it drives most of the advice.
- Tide state is entered by hand. Tide predictions aren't fetched yet.
- The bite score is a set of rules of thumb, not a calibrated model. Your catch log is what makes it specific to your water.
