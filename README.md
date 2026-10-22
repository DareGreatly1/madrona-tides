# Madrona Beach high tide

A rough, automatic estimate of the **actual** high tide at Madrona Beach on Camano Island, Washington. Once a day it reads the public tide, weather, and river feeds, rebuilds this page, and keeps the inputs so a later piling photo can be compared with the forecast.

**These are VERY rough estimates and should not be used to reduce your concern for your safety or property.**

**This is for informational purposes only. Do not make decisions based on this data.**

The page, after GitHub Pages is enabled:

https://daregreatly1.github.io/madrona-tides/

## The estimate

Coefficients are all in [`config.json`](config.json). Change those numbers and run the workflow again. Nothing else is hard-coded.

1. **Tide.** NOAA predicted high tide, station `9447929` (Coupeville, Penn Cove), datum MLLW, feet.
2. **Pressure.** Add `0.3937` inches of water for every millibar that sea-level pressure is below `1013.21`, and subtract the same amount when pressure is higher. That is the owner's formula `((mb - 1013.21) × -0.3937)`.
3. **Westerly wind.** Add `4` inches for every `10` mph of the westerly component at Ault Field / NAS Whidbey (KNUW).
4. **Skagit River.** Add `1.2` inches for every foot the Mount Vernon gauge (USGS `12200500`) is above `20` ft. At or below 20 ft the river term is zero. Flood stage is 28 ft.

The four pieces are added, and the result is the predicted actual height. Each high tide for about the next five days is listed with the tide and the three adjustments.

### Westerly component

Wind direction is the direction the wind **comes from**, in degrees clockwise from north.

The part that counts is the eastward component of that wind (air moving toward the east, which is a wind from the west):

```text
westerly mph = max(0, -speed × sin(direction))
```

- A west wind counts in full. Twenty mph from the west adds 8 inches.
- A southwest or northwest wind counts only its west-east part.
- Wind from the south, east, or southeast adds nothing. It is not subtracted. Madrona faces west onto Saratoga Passage, and the notes only add water for wind from the west.
- The sustained wind is used. Gusts are shown on the page and are not added.

Wind speed and direction come from the [api.weather.gov](https://api.weather.gov/) forecast grid for the KNUW coordinates. The National Weather Service grid for this point does not currently publish pressure, so the sea-level pressure forecast is the Open-Meteo value at those same coordinates. If a high tide is within two hours of the latest KNUW observation, that observed sea-level pressure is used instead. If the NWS grid starts publishing pressure, the build uses that automatically.

The Skagit height for a future high tide is the [National Water Prediction Service](https://api.water.noaa.gov/nwps/v1/gauges/MVEW1/stageflow) forecast for gauge `MVEW1` when the forecast covers that time. Otherwise the page uses the current USGS reading and says so.

### Flood flag

Both photographed floods (15 Nov 2021, 3:02 PM, and 27 Dec 2022, 8:45 AM) left **5 of 10** piling steps showing. On the scale in the notes, the lowest step is about a 10 ft tide and the steps are about a foot apart, so 5 steps showing is **15 ft**.

`likely_flood_ft` in `config.json` is **14.0 ft**: one foot below those photos, because the water was already over the berm and the formula only roughly fits. The flag is a highlight on this page, not a warning from any agency.

## Record a piling reading

Edit [`observations.csv`](observations.csv). One row per photo:

```csv
observed_at,steps_showing,actual_height_ft,notes
2026-10-21T15:10:00-07:00,8,,"Water around the 8th step. Count from the top."
```

- `observed_at` is Pacific time. Include the offset (`-07:00` in summer, `-08:00` in winter) so the comparison lands on the right high tide.
- `steps_showing` is how many of the 10 steps are still above the water.
- `actual_height_ft` can be left blank. The page then uses the owner's scale: height = 10 ft + (10 − steps) × 1 ft. You can also type the height yourself.
- Commit the file to `main` (or use the edit link on the page), then run **Daily forecast** from the Actions tab. The next morning's run will pick it up if you don't run it by hand.

The comparison uses a hindcast for the two historical photos, and `data/history.csv` for any later reading. That log has one row per high tide per day: the predicted tide, pressure, wind, river height, each adjustment, and the predicted actual height.

## Daily update

[`.github/workflows/daily-forecast.yml`](.github/workflows/daily-forecast.yml) runs at **13:30 UTC**, which is 5:30 AM PST and 6:30 AM PDT, and whenever someone starts it with **Run workflow**. GitHub sometimes starts a scheduled job later than the clock time.

The job fetches the feeds, rebuilds `site/index.html`, appends that day's rows to `data/history.csv` and `data/history.jsonl` (a second run the same day replaces that day's rows), commits the result, and deploys the `site/` folder with GitHub Pages.

A browser left open on the page reloads itself after that publish. It requests the small `version.json` file every few minutes, and again when the tab becomes visible, using a new address each time so GitHub Pages' cache cannot keep serving the previous timestamp. When the timestamp in that file differs from the page, the browser loads the new forecast. The last-updated time is shown under the title and in the footer. The check pauses while the tab is in the background.

No API keys are required.

### Turn the page on

The workflow has to be on `main`, and Pages has to use the Actions source. In the repository:

**Settings → Pages → Build and deployment → Source: GitHub Actions**

Then open **Actions → Daily forecast → Run workflow**. The live URL is printed on that run and is [https://daregreatly1.github.io/madrona-tides/](https://daregreatly1.github.io/madrona-tides/).

If the “Commit the forecast history” step fails and says the token cannot push, set **Settings → Actions → General → Workflow permissions → Read and write permissions** and run the workflow again. The page can still deploy without that step; the history file in the repo will not update until the push is allowed.

## Backtest

`python scripts/backtest.py` rebuilds [`data/backtest.json`](data/backtest.json) from NOAA predictions, the KNUW hourly archive (Iowa Environmental Mesonet), and the USGS gauge. The page recomputes both events with the current coefficients.

The owner's spreadsheet and the retrieved observations are both shown. With the original coefficients:

| Event | What was used | Estimate | Photographed | Estimate − photo |
| --- | --- | --- | --- | --- |
| 15 Nov 2021, 3:02 PM | Owner's sheet: tide 11.50 ft, 997.63 mb, west 48 mph, Skagit 33.93 ft | 15.00 ft | 15.0 ft | 0.00 ft |
| 15 Nov 2021 | NOAA high 11.70 ft at 2:31 PM; KNUW at 2:56 PM was 1005.0 mb and 45 mph from 260°; USGS at 3:00 PM was 33.66 ft and about 101,000 cfs | 14.80 ft | 15.0 ft | −0.20 ft |
| 27 Dec 2022, 8:45 AM | Owner's sheet: tide 12.90 ft, 977.31 mb, SSE 30 mph, Skagit 24.97 ft | 14.57 ft | 15.0 ft | −0.43 ft |
| 27 Dec 2022 | NOAA high 13.03 ft at 8:56 AM; KNUW at 8:53 AM was 978.0 mb and 26 mph from 140° (no westerly component); USGS at 8:45 AM was 24.95 ft and about 52,200 cfs | 14.68 ft | 15.0 ft | −0.32 ft |

November lines up with the owner's own inputs because those inputs, run through the written rules, add up to the 3.50 ft gap between the sheet's tide and the 15 ft piling. December does not: pressure and the river explain about 1.68 ft, and a SSE wind adds nothing under the westerly-component rule, leaving about 5 inches unaccounted for. The owner's tide column is also a bit below the NOAA high (11.50 vs 11.70, and 12.90 vs 13.03). The retrieved rows are the fairer check, because they do not reuse the numbers already written into the sheet. On those rows the formula was 2 inches low in November and 4 inches low in December. The sheet's Skagit heights are close to USGS (33.93 vs 33.66 ft, and 24.97 vs 24.95 ft). The November pressure in the sheet, 997.63 mb, matches the late morning rather than 3 PM, when KNUW had already risen to 1005 mb.

These are the only two floods in the notes. A close result is not a calibration.

## Run it locally

Python 3.11 or newer. The scripts use only the standard library.

```bash
python scripts/test_model.py
python scripts/backtest.py
python scripts/build_site.py
```

Open `site/index.html`.

## Sources

- [NOAA CO-OPS tide predictions, station 9447929](https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9447929)
- [NWS forecast](https://api.weather.gov/) at KNUW, and the [latest KNUW observation](https://api.weather.gov/stations/KNUW/observations/latest)
- [Open-Meteo](https://open-meteo.com/) sea-level pressure when the NWS grid has none
- [USGS 12200500](https://waterdata.usgs.gov/monitoring-location/12200500/), Skagit River near Mount Vernon
- [NWS river forecast MVEW1](https://water.noaa.gov/gauges/mvew1)
- Historical KNUW wind and pressure for the backtest: Iowa Environmental Mesonet ASOS archive
