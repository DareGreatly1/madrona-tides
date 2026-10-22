"""Render the static Madrona Beach page."""

from __future__ import annotations

import html
from datetime import datetime

import model

DISCLAIMER_ROUGH = (
    "These are VERY rough estimates and should not be used to reduce "
    "your concern for your safety or property."
)
DISCLAIMER_INFO = (
    "This is for informational purposes only. Do not make decisions based on this data."
)

# GitHub Pages caches files for about ten minutes and often ignores
# Cache-Control on the request. A new query string is a different cache
# key, so this poll reads the live version.json instead of yesterday's copy.
REFRESH_SCRIPT = """
<script>
(function () {
  var POLL_MS = 180000;
  var meta = document.querySelector('meta[name="forecast-generated-at"]');
  var current = meta ? meta.getAttribute("content") : "";
  var note = document.getElementById("refresh-note");
  var timer = null;

  function setNote(text) {
    if (note) note.textContent = text;
  }

  function check() {
    if (document.visibilityState === "hidden") return;
    fetch("version.json?t=" + Date.now(), {
      cache: "no-store",
      headers: { "Accept": "application/json" }
    }).then(function (response) {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }).then(function (data) {
      var published = data && data.generated_at;
      if (!published || published === current) {
        setNote("This page checks for the morning update every few minutes.");
        var here = new URL(window.location.href);
        if (here.searchParams.has("v")) {
          here.searchParams.delete("v");
          history.replaceState(null, "", here.pathname + here.search + here.hash);
        }
        return;
      }
      var now = Date.now();
      var previous = Number(sessionStorage.getItem("madrona-tide-reload-at") || 0);
      if (previous && now - previous < 45000) return;
      sessionStorage.setItem("madrona-tide-reload-at", String(now));
      setNote("A new forecast is published. Refreshing.");
      var next = new URL(window.location.href);
      next.searchParams.set("v", String(published) + "-" + now);
      window.location.replace(next.toString());
    }).catch(function () {
      setNote("Could not check for a new forecast. Trying again shortly.");
    });
  }

  function start() {
    if (timer !== null) return;
    timer = setInterval(check, POLL_MS);
  }

  function stop() {
    if (timer === null) return;
    clearInterval(timer);
    timer = null;
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      stop();
    } else {
      check();
      start();
    }
  });
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) check();
  });
  if (document.visibilityState !== "hidden") start();
  setTimeout(check, 4000);
})();
</script>
"""


def version_payload(generated_at: datetime, run_date: str) -> dict:
    """Tiny file the open page polls. Keep it separate from latest.json."""
    return {
        "generated_at": generated_at.isoformat(),
        "run_date": run_date,
    }


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_ft(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f} ft"


def fmt_in(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) < 0.05:
        return "0 in"
    sign = "+" if value > 0 else "−"
    return f"{sign}{abs(value):.1f} in"


def fmt_signed_ft(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.2f} ft"


def fmt_when(moment: datetime) -> str:
    hour = moment.strftime("%I").lstrip("0") or "0"
    clock = f"{hour}:{moment.strftime('%M %p')}"
    zone = moment.tzname() or ""
    return f"{moment.strftime('%A, %B')} {moment.day} · {clock} {zone}".strip()


def fmt_short(moment: datetime) -> str:
    hour = moment.strftime("%I").lstrip("0") or "0"
    return f"{moment.strftime('%b')} {moment.day}, {hour}:{moment.strftime('%M %p')}"


def fmt_num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def steps_phrase(steps: float | None, cfg: dict) -> str:
    if steps is None:
        return "—"
    count = cfg["pilings"]["step_count"]
    if steps > count + 0.05:
        return f"water below the lowest step (all {count} showing)"
    if steps < -0.05:
        return "water above the top step"
    shown = max(0.0, steps)
    return f"about {shown:.1f} of {count} steps showing"


def meter(actual: float | None, threshold: float, scale: float = 16.0) -> str:
    if actual is None:
        return ""
    percent = max(0.0, min(100.0, actual / scale * 100.0))
    mark = max(0.0, min(100.0, threshold / scale * 100.0))
    return (
        f'<div class="meter" aria-hidden="true">'
        f'<span class="meter-fill" style="width:{percent:.1f}%"></span>'
        f'<span class="meter-mark" style="left:{mark:.1f}%"></span>'
        f"</div>"
    )


def tide_card(tide: dict, cfg: dict, featured: bool = False) -> str:
    actual = tide.get("predicted_actual_ft")
    flood = bool(tide.get("likely_flood"))
    classes = "card tide"
    if featured:
        classes += " featured"
    if flood:
        classes += " flood"
    if tide.get("passed"):
        classes += " passed"
    status = ""
    if tide.get("incomplete"):
        status = '<p class="status incomplete">Incomplete. A source was missing, so this is not a full estimate.</p>'
    elif flood:
        status = '<p class="status flood-label">Likely flooding on this rough scale.</p>'
    elif tide.get("passed"):
        status = '<p class="status quiet">Already passed.</p>'
    else:
        status = '<p class="status quiet">Below the flood flag.</p>'

    wind_detail = "—"
    if tide.get("wind_mph") is not None:
        gust = ""
        if tide.get("wind_gust_mph") is not None:
            gust = f", gusts {tide['wind_gust_mph']:.0f} mph"
        wind_detail = (
            f"{tide['wind_mph']:.0f} mph from {esc(tide.get('wind_compass'))} "
            f"({tide['wind_dir_deg']:.0f}°){gust}. "
            f"Westerly part {tide['westerly_mph']:.0f} mph."
        )
    river_detail = "—"
    if tide.get("river_ft") is not None:
        river_detail = f"{tide['river_ft']:.2f} ft · {esc(tide.get('river_source'))}"

    return f"""
<article class="{classes}">
  <p class="when">{esc(fmt_when(tide['time']))}</p>
  <p class="actual">{esc(fmt_ft(actual))}</p>
  <p class="actual-label">predicted actual height</p>
  {meter(actual, cfg['flood']['likely_flood_ft'])}
  {status}
  <dl>
    <div><dt>NOAA predicted tide</dt><dd>{esc(fmt_ft(tide.get('predicted_tide_ft')))}</dd></div>
    <div><dt>Pressure</dt><dd>{esc(fmt_in(tide.get('pressure_adjust_in')))}<span>{esc(fmt_num(tide.get('pressure_mb'), 1))} mb · {esc(tide.get('pressure_source'))}</span></dd></div>
    <div><dt>Westerly wind</dt><dd>{esc(fmt_in(tide.get('wind_adjust_in')))}<span>{wind_detail}</span></dd></div>
    <div><dt>Skagit River</dt><dd>{esc(fmt_in(tide.get('river_adjust_in')))}<span>{river_detail}</span></dd></div>
    <div><dt>Piling steps</dt><dd>{esc(steps_phrase(tide.get('steps_showing'), cfg))}</dd></div>
  </dl>
</article>
"""


def formula_block(result: dict) -> str:
    return (
        "<ul class=\"parts\">"
        f"<li>Tide {esc(fmt_ft(result['predicted_tide_ft']))}</li>"
        f"<li>Pressure {esc(fmt_in(result['pressure_adjust_in']))} ({esc(fmt_num(result['pressure_mb'], 1))} mb)</li>"
        f"<li>Wind {esc(fmt_in(result['wind_adjust_in']))} "
        f"({esc(fmt_num(result['westerly_mph'], 0))} mph westerly, from {esc(result['wind_compass'])})</li>"
        f"<li>Skagit {esc(fmt_in(result['river_adjust_in']))} (gauge {esc(fmt_ft(result['river_ft']))})</li>"
        f"<li><strong>Estimate {esc(fmt_ft(result['predicted_actual_ft']))}</strong></li>"
        "</ul>"
    )


def backtest_section(backtest: dict | None, cfg: dict) -> str:
    if not backtest:
        return "<section><h2>Past floods</h2><p>No backtest file has been generated yet.</p></section>"
    cards = []
    for event in backtest.get("events") or []:
        owner = event["owner_inputs"]
        retrieved = event["retrieved"]
        owner_now = model.apply_formula(
            owner["predicted_tide_ft"], owner["pressure_mb"], owner["wind_mph"],
            owner["wind_dir_deg"], owner["river_ft"], cfg,
        )
        retrieved_now = model.apply_formula(
            retrieved["predicted_tide_ft"], retrieved["pressure_mb"], retrieved["wind_mph"],
            retrieved["wind_dir_deg"], retrieved["river_ft"], cfg,
        )
        observed = event["observed_height_ft"]
        cards.append(f"""
<article class="card event">
  <h3>{esc(event['label'])}</h3>
  <p>{esc(event['narrative'])}</p>
  <figure>
    <img src="{esc(event['image'])}" alt="Piling photo from {esc(event['label'])} used to read the actual tide.">
    <figcaption>Reference photo from the owner's notes. The spreadsheet reads this as {esc(event['observed_steps'])} steps showing, {esc(fmt_ft(observed))}.</figcaption>
  </figure>
  <h4>Using the numbers in the owner's spreadsheet</h4>
  <p class="fine">Tide {esc(fmt_ft(owner['predicted_tide_ft']))}, pressure {esc(fmt_num(owner['pressure_mb'], 2))} mb ({esc(owner['pressure_inhg'])} inHg), wind {esc(owner['wind_text'])}, Skagit {esc(fmt_ft(owner['river_ft']))}.</p>
  {formula_block(owner_now)}
  <p>Photographed height {esc(fmt_ft(observed))}. Estimate minus photographed height: <strong>{esc(fmt_signed_ft(owner_now['predicted_actual_ft'] - observed))}</strong>.</p>
  <h4>Using data retrieved for that hour</h4>
  <p class="fine">NOAA high at {esc(fmt_short(datetime.fromisoformat(retrieved['tide_time'])))} was {esc(fmt_ft(retrieved['predicted_tide_ft']))}. KNUW at {esc(fmt_short(datetime.fromisoformat(retrieved['weather_time'])))}: sea-level pressure {esc(fmt_num(retrieved['pressure_mb'], 1))} mb, wind {esc(fmt_num(retrieved['wind_mph'], 0))} mph from {esc(model.compass(retrieved['wind_dir_deg']))} ({esc(fmt_num(retrieved['wind_dir_deg'], 0))}°). USGS gauge {esc(fmt_ft(retrieved['river_ft']))}{('' if retrieved.get('river_cfs') is None else ', about ' + format(retrieved['river_cfs'], ',.0f') + ' cfs')}.</p>
  {formula_block(retrieved_now)}
  <p>Photographed height {esc(fmt_ft(observed))}. Estimate minus photographed height: <strong>{esc(fmt_signed_ft(retrieved_now['predicted_actual_ft'] - observed))}</strong>.</p>
</article>
""")
    return f"""
<section id="backtest">
  <h2>The two photographed floods</h2>
  <p>{esc(backtest.get('observed_height_note') or '')} A negative difference means the formula came in low. These two days are the only floods the formula was built from, so a close result is a check that the arithmetic matches the notes, not proof that the next storm will match.</p>
  {''.join(cards)}
</section>
"""


def as_float(value):
    if value is None or value == "":
        return None
    return float(value)


def observation_rows(observations: list[dict], history: list[dict], backtest: dict | None, cfg: dict) -> str:
    backtest_by_id = {}
    if backtest:
        for event in backtest.get("events") or []:
            backtest_by_id[event["photo_time"]] = event
    rows = []
    if not observations:
        return "<p>No readings in observations.csv yet.</p>"
    for obs in observations:
        when = obs["observed_at"]
        predicted = None
        source = "No stored forecast for that high tide yet."
        matched_event = backtest_by_id.get(when.isoformat())
        if matched_event is None:
            # Match on the clock time even if the offset formatting differs.
            for event in (backtest or {}).get("events") or []:
                event_time = datetime.fromisoformat(event["photo_time"])
                if abs((event_time - when).total_seconds()) < 60:
                    matched_event = event
                    break
        if matched_event:
            retrieved = matched_event["retrieved"]
            result = model.apply_formula(
                retrieved["predicted_tide_ft"], retrieved["pressure_mb"], retrieved["wind_mph"],
                retrieved["wind_dir_deg"], retrieved["river_ft"], cfg,
            )
            predicted = result["predicted_actual_ft"]
            source = "Hindcast from NOAA, KNUW, and USGS for that hour."
        else:
            best = None
            best_key = None
            for run in history:
                for tide in run.get("tides") or []:
                    tide_time = datetime.fromisoformat(tide["high_tide_time"])
                    gap = abs((tide_time - when).total_seconds())
                    if gap > 6 * 3600 or tide.get("predicted_actual_ft") is None:
                        continue
                    same_day = run.get("run_date") == tide_time.astimezone(when.tzinfo).date().isoformat()
                    key = (0 if same_day else 1, gap)
                    if best_key is None or key < best_key:
                        best_key = key
                        best = tide
            if best is not None:
                predicted = as_float(best.get("predicted_actual_ft"))
                source = f"Forecast stored for the {fmt_short(datetime.fromisoformat(best['high_tide_time']))} high tide."
        diff = None if predicted is None or obs.get("actual_height_ft") is None else predicted - obs["actual_height_ft"]
        rows.append(f"""
<tr>
  <td>{esc(fmt_when(when))}</td>
  <td>{esc(obs.get('steps_showing') if obs.get('steps_showing') is not None else '—')}</td>
  <td>{esc(fmt_ft(obs.get('actual_height_ft')))}</td>
  <td>{esc(fmt_ft(predicted))}<span class="fine">{esc(source)}</span></td>
  <td>{esc(fmt_signed_ft(diff))}</td>
</tr>
""")
    return f"""
<div class="table-wrap">
<table>
  <thead>
    <tr><th>Observed</th><th>Steps</th><th>Height</th><th>Predicted actual</th><th>Predicted − observed</th></tr>
  </thead>
  <tbody>
    {''.join(rows)}
  </tbody>
</table>
</div>
"""


def render_page(context: dict) -> str:
    cfg = context["config"]
    tides = context["tides"]
    upcoming = [tide for tide in tides if not tide.get("passed")]
    featured = upcoming[0] if upcoming else (tides[-1] if tides else None)
    cards = []
    for tide in tides:
        cards.append(tide_card(tide, cfg, featured=featured is tide))
    current = context.get("current") or {}
    knuw = current.get("knuw") or {}
    usgs = current.get("usgs") or {}
    warnings = context.get("warnings") or []
    warning_html = ""
    if warnings:
        items = "".join(f"<li>{esc(item)}</li>" for item in warnings)
        warning_html = f'<ul class="warnings">{items}</ul>'
    repo = cfg.get("repository", "DareGreatly1/madrona-tides")
    edit_url = f"https://github.com/{repo}/edit/main/observations.csv"
    generated = context["generated_at"]
    station = context.get("station_name") or cfg["tide"]["station_id"]
    flood_ft = cfg["flood"]["likely_flood_ft"]
    photo_ft = cfg["flood"]["photographed_flood_ft"]
    per_mb = cfg["pressure"]["inches_per_mb"]
    reference = cfg["pressure"]["reference_mb"]
    per_10 = cfg["wind"]["inches_per_10_mph"]
    per_foot = cfg["river"]["inches_per_foot_above_baseline"]
    baseline = cfg["river"]["baseline_ft"]
    flood_stage = cfg["river"]["flood_stage_ft"]

    knuw_bits = "Latest KNUW observation was not available."
    if knuw.get("time"):
        wind = "calm" if not knuw.get("wind_mph") else (
            f"{knuw['wind_mph']:.0f} mph from {knuw.get('wind_compass') or 'an unknown direction'}"
        )
        pressure = fmt_num(knuw.get("pressure_mb"), 1)
        knuw_bits = (
            f"KNUW at {fmt_short(knuw['time'])}: sea-level pressure {pressure} mb, wind {wind}."
        )
    river_bits = "Current Skagit gauge reading was not available."
    if usgs.get("stage_ft") is not None:
        flow = ""
        if usgs.get("flow_cfs") is not None:
            flow = f", {usgs['flow_cfs']:,.0f} cfs"
        river_bits = (
            f"Skagit at Mount Vernon {usgs['stage_ft']:.2f} ft{flow} "
            f"at {fmt_short(usgs['time'])}. Flood stage is {flood_stage:.0f} ft."
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Madrona Beach high tide</title>
<meta name="description" content="A rough daily estimate of the actual high tide at Madrona Beach, Camano Island, Washington.">
<meta name="forecast-generated-at" content="{esc(generated.isoformat())}">
<style>
:root {{
  --bg: #f3f0e8;
  --card: #fffdf8;
  --ink: #1d2430;
  --muted: #5e6874;
  --line: #e3dcd0;
  --water: #1c4d5e;
  --flood-bg: #fff0e4;
  --flood: #8d3412;
  --warn-bg: #fff6df;
  --warn: #6d3d10;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 17px/1.5 "Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif;
}}
main {{
  max-width: 42rem;
  margin: 0 auto;
  padding: 1rem 1rem 3rem;
}}
h1, h2, h3, h4 {{ font-weight: 600; line-height: 1.2; }}
h1 {{ font-size: 2rem; margin: 0.2rem 0; }}
h2 {{ font-size: 1.4rem; margin: 2rem 0 0.6rem; }}
h3 {{ margin: 0 0 0.4rem; font-size: 1.2rem; }}
h4 {{ margin: 1rem 0 0.3rem; font-size: 1rem; }}
p {{ margin: 0.5rem 0; }}
a {{ color: var(--water); }}
.banner {{
  background: var(--warn-bg);
  color: var(--warn);
  border: 2px solid #e2c48a;
  border-radius: 12px;
  padding: 0.9rem 1rem;
  margin: 0 0 1rem;
}}
.banner strong {{ display: block; font-size: 1.05rem; margin-bottom: 0.25rem; }}
.lede {{ color: var(--muted); margin-top: 0; }}
.updated {{ margin: 0.15rem 0 0; font-weight: 600; }}
#refresh-note {{ margin-top: 0.1rem; }}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 1rem 1rem 0.8rem;
  margin: 0.8rem 0;
}}
.tide.featured {{ border-color: #b7c9c6; }}
.tide.flood {{ background: var(--flood-bg); border-color: #efc2a4; }}
.tide.passed {{ opacity: 0.78; }}
.when {{ margin: 0; color: var(--muted); }}
.actual {{
  font-size: 2.6rem;
  line-height: 1;
  margin: 0.35rem 0 0;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}}
.featured .actual {{ font-size: 3.4rem; }}
.actual-label {{ margin: 0.2rem 0 0.6rem; color: var(--muted); }}
.status {{ font-weight: 600; }}
.status.quiet {{ color: var(--muted); font-weight: 500; }}
.status.flood-label {{ color: var(--flood); }}
.status.incomplete {{ color: var(--flood); }}
dl {{ margin: 0.4rem 0 0; }}
dl div {{
  display: grid;
  grid-template-columns: 9.5rem 1fr;
  gap: 0.4rem;
  padding: 0.45rem 0;
  border-top: 1px solid var(--line);
}}
dt {{ color: var(--muted); }}
dd {{ margin: 0; }}
dd span, .fine {{
  display: block;
  color: var(--muted);
  font-size: 0.92rem;
}}
.meter {{
  position: relative;
  height: 0.55rem;
  background: #ece4d6;
  border-radius: 99px;
  margin: 0.3rem 0 0.7rem;
}}
.meter-fill {{
  display: block;
  height: 100%;
  background: var(--water);
  border-radius: 99px;
}}
.flood .meter-fill {{ background: var(--flood); }}
.meter-mark {{
  position: absolute;
  top: -0.2rem;
  width: 2px;
  height: 0.95rem;
  background: var(--flood);
}}
.warnings {{
  background: var(--flood-bg);
  border-radius: 12px;
  padding: 0.6rem 0.9rem 0.6rem 1.6rem;
}}
.table-wrap {{ overflow-x: auto; }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  font-size: 0.95rem;
}}
th, td {{
  text-align: left;
  vertical-align: top;
  padding: 0.55rem 0.45rem;
  border-bottom: 1px solid var(--line);
}}
th {{ color: var(--muted); font-weight: 600; }}
.parts {{ margin: 0.3rem 0 0.4rem; padding-left: 1.1rem; }}
figure {{ margin: 0.6rem 0; }}
img {{ width: 100%; height: auto; border-radius: 10px; }}
figcaption {{ color: var(--muted); font-size: 0.92rem; }}
footer {{ color: var(--muted); font-size: 0.95rem; margin-top: 2rem; }}
code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em; }}
@media (max-width: 36rem) {{
  dl div {{ grid-template-columns: 1fr; gap: 0.1rem; }}
  .actual, .featured .actual {{ font-size: 2.5rem; }}
}}
</style>
</head>
<body>
<main>
  <div class="banner">
    <strong>{esc(DISCLAIMER_ROUGH)}</strong>
    {esc(DISCLAIMER_INFO)}
  </div>
  {warning_html}
  <p class="lede">{esc(cfg['location_name'])}, {esc(cfg['location_detail'])}</p>
  <h1>Actual high tide</h1>
  <p class="updated">Last updated <time id="last-updated" datetime="{esc(generated.isoformat())}">{esc(fmt_when(generated))}</time></p>
  <p class="fine" id="refresh-note">This page checks for the morning update every few minutes.</p>
  <noscript><p class="fine">Reload this page to see a newer forecast.</p></noscript>
  <p class="lede">Astronomical tide plus rough allowances for air pressure, westerly wind, and the Skagit River. A high tide is flagged at {esc(fmt_ft(flood_ft, 1))}.</p>

  <section id="forecast">
    <h2>High tides</h2>
    {''.join(cards) if cards else '<p>No high tides were returned.</p>'}
    <p class="fine">The mark on each bar is the {esc(fmt_ft(flood_ft, 1))} flood flag. The photographed floods were about {esc(fmt_ft(photo_ft, 1))}.</p>
  </section>

  <section id="now">
    <h2>Right now</h2>
    <div class="card">
      <p>{esc(knuw_bits)}</p>
      <p>{esc(river_bits)}</p>
      <p class="fine">{esc(current.get('pressure_note') or '')} {esc(current.get('river_note') or '')}</p>
    </div>
  </section>

  <section id="compare">
    <h2>Predicted and observed</h2>
    <p>The pilings have {esc(cfg['pilings']['step_count'])} steps about a foot apart. The lowest step is about a {esc(fmt_ft(cfg['pilings']['feet_at_lowest_step'], 0))} tide, so 9 steps showing is about 11 ft and 5 steps showing is about 15 ft. Photograph the steps at a high tide and add a row to <code>observations.csv</code>.</p>
    {observation_rows(context.get('observations') or [], context.get('history') or [], context.get('backtest'), cfg)}
    <p><a href="{esc(edit_url)}">Add a reading on GitHub</a>. Use Pacific time, for example <code>2026-10-21T15:10:00-07:00</code>. You can leave the height blank and enter only the steps still showing. Then run the “Daily forecast” workflow, or wait for the next morning, and the comparison will include it. Past forecasts are kept in <code>data/history.csv</code>.</p>
  </section>

  {backtest_section(context.get('backtest'), cfg)}

  <section id="method">
    <h2>How the estimate is made</h2>
    <p>The working hypothesis, with the numbers currently in <code>config.json</code>:</p>
    <ul>
      <li>Start with the NOAA predicted high tide at station {esc(cfg['tide']['station_id'])} ({esc(station)}), datum MLLW, in feet.</li>
      <li>Pressure. Add {esc(per_mb)} inches of water for every millibar that sea-level pressure is below {esc(reference)} mb, and subtract the same amount when pressure is higher.</li>
      <li>Westerly wind. Add {esc(per_10)} inches for every 10 mph of the westerly component at {esc(cfg['weather']['label'])}. Direction is where the wind comes from. Due west counts in full. Southwest or northwest counts only the part that is from the west. South, east, and southeast count as zero and are not subtracted. Sustained wind is used. Gusts are shown and not added.</li>
      <li>Skagit River. Add {esc(per_foot)} inches for every foot the Mount Vernon gauge is above {esc(f'{baseline:.0f}')} ft. At or below {esc(f'{baseline:.0f}')} ft the river term is zero. Flood stage on that gauge is {esc(f'{flood_stage:.0f}')} ft. A future high tide uses the National Water Prediction Service forecast for {esc(cfg['river']['nws_lid'])} when it covers that time, and the current USGS reading otherwise.</li>
    </ul>
    <p>{esc(cfg['flood']['basis'])}</p>
    <p>Change the coefficients in <code>config.json</code> and run the daily workflow again. The page and the flood comparison both use that file.</p>
  </section>

  <section id="sources">
    <h2>Sources</h2>
    <ul>
      <li><a href="https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id={esc(cfg['tide']['station_id'])}">NOAA tide predictions, station {esc(cfg['tide']['station_id'])}</a></li>
      <li><a href="https://api.weather.gov/points/{cfg['weather']['latitude']},{cfg['weather']['longitude']}">NWS forecast grid for KNUW</a> and the <a href="https://api.weather.gov/stations/KNUW/observations/latest">latest KNUW observation</a></li>
      <li><a href="https://open-meteo.com/">Open-Meteo</a> sea-level pressure at the KNUW coordinates, used when the NWS grid does not publish pressure</li>
      <li><a href="https://waterdata.usgs.gov/monitoring-location/{esc(cfg['river']['usgs_site'])}/">USGS {esc(cfg['river']['usgs_site'])}, Skagit River near Mount Vernon</a></li>
      <li><a href="https://water.noaa.gov/gauges/{esc(cfg['river']['nws_lid']).lower()}">NWS / NWRFC forecast, {esc(cfg['river']['nws_lid'])}</a></li>
    </ul>
  </section>

  <footer>
    <div class="banner">
      <strong>{esc(DISCLAIMER_ROUGH)}</strong>
      {esc(DISCLAIMER_INFO)}
    </div>
    <p>Last updated <time datetime="{esc(generated.isoformat())}">{esc(fmt_when(generated))}</time>. Not a NOAA product and not a flood warning. The two historical floods are the whole calibration set.</p>
  </footer>
</main>
{REFRESH_SCRIPT}
</body>
</html>
"""
