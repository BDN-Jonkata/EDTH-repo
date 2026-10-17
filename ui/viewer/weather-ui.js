/*
 * The weather and sky controls of the left panel: fog, rain and wind toggles with a strength each,
 * a fixed night, and a sky (date, hour, place) that follows the season. It only edits the two settings
 * `weather` (text such as 'fog:0.5+wind') and `sky` (null or { date, hour, lat, lon, time_scale });
 * app.js keeps the state and runs the simulation.
 */
(function (global) {
  const W = global.Weather;
  const ROWS = [['fog', 'Fog'], ['rain', 'Rain'], ['wind', 'Wind'], ['night', 'Night (fixed)']];
  const NOTES = {
    fog: 'EO range cut, noisier, fewer detections.',
    rain: 'radar clutter and noisier radar.',
    wind: 'microphones much noisier, fewer detections.',
    night: 'visible cameras nearly blind; thermal, radar, RF and mics unaffected.',
  };
  // examples only: where the village is has not been decided
  const PLACES = { kyiv: ['Kyiv', 50.45, 30.52], berlin: ['Berlin', 52.52, 13.4], tallinn: ['Tallinn', 59.44, 24.75], madrid: ['Madrid', 40.42, -3.7], equator: ['Equator', 0, 0] };
  const DRAFT = { date: '2026-06-21', hour: 12, lat: 50.45, lon: 30.52, time_scale: 1 };
  const $ = (id) => document.getElementById(id);
  let onChange = () => {};
  let draft = Object.assign({}, DRAFT);

  const hhmm = (h) => String(Math.floor(h)).padStart(2, '0') + ':' + String(Math.round((h % 1) * 60) % 60).padStart(2, '0');

  // text for the note under the toggles
  function describe(weather) {
    const effects = W.parseWeather(weather), names = Object.keys(effects);
    if (!names.length) return 'Clear: all sensors nominal.';
    return names.map((n) => n[0].toUpperCase() + n.slice(1) + (effects[n] < 1 ? ' ' + Math.round(effects[n] * 100) + ' %' : '') + ': ' + NOTES[n]).join(' ');
  }

  // ------------------------------------------------------------ weather toggles
  function buildWeather() {
    $('wxList').innerHTML = ROWS.map(([id, label]) =>
      '<div class="wxrow"><label class="lyr"><span class="n">' + label + '</span><input class="sw" type="checkbox" data-wx="' + id + '"></label>' +
      '<input type="range" data-wxs="' + id + '" min="10" max="100" step="5" value="100" aria-label="' + label + ' strength"><span class="mono" data-wxv="' + id + '">100%</span></div>').join('');
    $('wxList').addEventListener('input', readWeather);
  }
  function readWeather() {
    const effects = {};
    ROWS.forEach(([id]) => {
      const on = document.querySelector('[data-wx="' + id + '"]').checked, s = +document.querySelector('[data-wxs="' + id + '"]').value;
      document.querySelector('[data-wxv="' + id + '"]').textContent = s + '%';
      if (on) effects[id] = s / 100;
    });
    onChange(W.formatWeather(effects), currentSky());
  }
  function showWeather(weather) {
    const effects = W.parseWeather(weather);
    ROWS.forEach(([id]) => {
      document.querySelector('[data-wx="' + id + '"]').checked = id in effects;
      const s = Math.round((effects[id] || 1) * 100);
      document.querySelector('[data-wxs="' + id + '"]').value = s;
      document.querySelector('[data-wxv="' + id + '"]').textContent = s + '%';
    });
  }

  // ------------------------------------------------------------ sky
  function buildSky() {
    $('skyBox').innerHTML =
      '<label class="lyr"><span class="n">Day and night follow the sky</span><input class="sw" type="checkbox" id="skyOn"></label>' +
      '<fieldset class="comms" id="skyFields" disabled><legend>Date, hour and place</legend>' +
      '<label class="fld">Date<input class="inp mono" id="skyDate" type="date"></label>' +
      '<label class="fld"><span style="display:flex;justify-content:space-between">Hour at the start <span class="mono" style="color:#C9D1DB" id="skyHourVal"></span></span>' +
      '<div class="skybar" id="skyBar" aria-hidden="true"></div><input type="range" id="skyHour" min="0" max="23.75" step="0.25" style="width:100%;accent-color:#3FC1D9"></label>' +
      '<label class="fld">Place<select class="inp" id="skyPlace">' + Object.keys(PLACES).map((k) => '<option value="' + k + '">' + PLACES[k][0] + '</option>').join('') + '<option value="custom">Custom</option></select></label>' +
      '<div class="row"><label class="fld" style="flex:1 1 0">Latitude<input class="inp mono" id="skyLat" type="number" min="-90" max="90" step="0.01"></label>' +
      '<label class="fld" style="flex:1 1 0">Longitude<input class="inp mono" id="skyLon" type="number" min="-180" max="180" step="0.01"></label></div>' +
      '<label class="fld">Clock seconds per run second<input class="inp mono" id="skyScale" type="number" min="0" step="1"></label>' +
      '<p class="note" id="skyNote"></p></fieldset>';
    $('skyBox').addEventListener('input', onSkyInput);
    $('skyBox').addEventListener('change', onSkyInput);
  }
  function onSkyInput(e) {
    if (e.target.id === 'skyPlace' && PLACES[e.target.value]) { $('skyLat').value = PLACES[e.target.value][1]; $('skyLon').value = PLACES[e.target.value][2]; }
    if (e.target.id === 'skyLat' || e.target.id === 'skyLon') $('skyPlace').value = 'custom';
    $('skyFields').disabled = !$('skyOn').checked;
    readWeather();
  }
  // the sky the controls describe, or null when switched off or not valid (the note says why)
  function currentSky() {
    if (!$('skyOn').checked) { draw(null); return null; }
    const sky = { date: $('skyDate').value, hour: +$('skyHour').value, lat: parseFloat($('skyLat').value), lon: parseFloat($('skyLon').value), time_scale: parseFloat($('skyScale').value) };
    try { W.makeSky(sky); } catch (e) { $('skyNote').textContent = e.message; return null; }
    if (draft.utc_offset_h !== undefined) sky.utc_offset_h = draft.utc_offset_h;
    draft = sky;
    draw(sky);
    return sky;
  }
  // sunrise and sunset on the slider, and what the sky does at the start
  function draw(sky) {
    $('skyHourVal').textContent = hhmm(+$('skyHour').value);
    if (!sky) return;
    const k = W.makeSky(sky), t = W.sunTimes(k), rise = t.sunrise, set = t.sunset;
    $('skyBar').style.background = skyGradient(k, rise, set);
    const daylight = hhmm(W.skyDaylightHours(k)).replace(':', ' h ') + ' min';
    const when = rise === null || set === null ? 'No sunrise or sunset on this date here. ' : 'Sunrise ' + hhmm(rise) + ', sunset ' + hhmm(set) + ' (local clock). ';
    $('skyNote').textContent = when + 'Daylight ' + daylight + '. Night strength at the start: ' + W.skyNightStrength(k, 0).toFixed(2) + (k.timeScale > 0 ? ', changing during the run.' : '.');
  }
  // dark outside daylight, light between sunrise and sunset, over the 24 h of the slider
  function skyGradient(k, rise, set) {
    const light = '#3A4A66', dark = '#0B0F14', pct = (h) => (h / 24 * 100).toFixed(1) + '%';
    if (rise === null || set === null) return W.skyElevationDeg(Object.assign({}, k, { hour: 12, timeScale: 0 }), 0) >= 0 ? light : dark;
    const [from, to, inside, outside] = rise < set ? [rise, set, light, dark] : [set, rise, dark, light];
    return 'linear-gradient(90deg,' + outside + ' ' + pct(from) + ',' + inside + ' ' + pct(from) + ',' + inside + ' ' + pct(to) + ',' + outside + ' ' + pct(to) + ')';
  }
  function showSky(sky) {
    const s = sky || draft;
    $('skyOn').checked = !!sky;
    $('skyFields').disabled = !sky;
    $('skyDate').value = s.date; $('skyHour').value = s.hour; $('skyLat').value = s.lat; $('skyLon').value = s.lon; $('skyScale').value = s.time_scale === undefined ? 1 : s.time_scale;
    const place = Object.keys(PLACES).find((k) => PLACES[k][1] === s.lat && PLACES[k][2] === s.lon);
    $('skyPlace').value = place || 'custom';
    $('skyNote').textContent = '';
    draw(sky ? s : null);
  }

  function init(handler) { onChange = handler; buildWeather(); buildSky(); }
  function show(weather, sky) { showWeather(weather); showSky(sky); }

  global.WeatherUI = { init, show, describe };
})(window);
