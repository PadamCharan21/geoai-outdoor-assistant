# Fieldnote GeoAI | 5-slide presentation source

## 1. The outdoor decision
A forecast describes weather. A useful plan answers: which nearby place, at what hour, for this person? The same activity can be comfortable at one venue and unsuitable nearby.

## 2. What happens after a question
Question → extract activity, area, time and personal flags → geocode area → find mapped venues and nearby context → fetch hourly forecast + PM2.5 at each candidate → score place-hour pairs → local SLM summarizes evidence.

## 3. Worked example
“I have mild asthma. Where's good for a morning walk near Powai tomorrow?” The app compares mapped parks and other matching places over morning forecast hours, checks rain, heat, wind, UV and PM2.5 at each point, applies a stricter PM2.5 caution, and returns the best available evidence plus alternatives.

## 4. Model and live data
Qwen2.5-0.5B-Instruct (0.5B, Apache-2.0), run locally. Open-Meteo geocoding, weather, and air-quality APIs; OpenStreetMap via Overpass. Python owns the ranking; the model only writes a concise summary. Public model repo and endpoint must be added after publishing and deployment.

## 5. Limits and next steps
Forecasts are model grids, not venue sensors. OSM coverage and opening hours vary. There is no live traffic feed or medical assessment. Scores compare options; they do not guarantee safety. Add persistent endpoint hosting, publish the public model repository, and validate live queries across the judging region.

