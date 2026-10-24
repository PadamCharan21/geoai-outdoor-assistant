# Fieldnote GeoAI

A live-data assistant that compares **place × hour** for ten outdoor activities. It fetches a location, nearby mapped venues and context, hourly weather, and PM2.5; a locally running Qwen2.5-0.5B-Instruct summarizes the evidence. Python scores the candidate windows deterministically, so the model does not choose the facts or fabricate the weather.

## Run locally

Python 3.11+ is required. The first request downloads the open model weights from Hugging Face (about 1 GB); CPU inference works but can be slow. For a GPU, install a CUDA-compatible PyTorch build first.

```powershell
cd geoai-outdoor-assistant
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install .

uvicorn app.main:app --reload --port 8000
```

Set any model options from .env.example as process environment variables. Open http://localhost:8000. The API is at http://localhost:8000/docs. Try:

```json
{"question":"I have mild asthma. Where's good for a morning walk near Powai, Mumbai tomorrow?"}
```

`POST /api/recommend` accepts a free-form `question` and optional `activity`, `location`, `radius_km` (2–50), and `personal` object. Missing activity or location returns a clarification error. `GET /health` is a lightweight liveness check; it does not load the model.

## Data and reasoning

- **Open-Meteo Geocoding API** resolves the user-provided area.
- **OpenStreetMap via Overpass API** supplies nearby activity venues, parks, roads, water bodies, and mapped industrial land use. OSM results are filtered and ranked by straight-line distance. Mapped features do not establish traffic volume or pollution exposure.
- **Open-Meteo Forecast API** supplies seven days of hourly temperature, apparent temperature, precipitation probability, wind speed/direction/gusts, and UV.
- **Open-Meteo Air Quality API** supplies seven days of hourly PM2.5, PM10, and US AQI.
- A deterministic, activity-aware rule score compares forecast hours at up to four venues. Personal flags can make heat and particle cautions stricter. Nearby mapped green space can add a small transparent score bonus; mapped industry upwind in the forecast wind can add a caution and penalty; a very close mapped major road is flagged without claiming traffic measurements. Weekend requests compare Saturday and Sunday separately. Scores are comparative heuristics, not safety certifications. The local model only summarizes the resulting evidence.

OpenStreetMap attribution is displayed in the interface and API response as **© OpenStreetMap contributors**. The process caches identical upstream requests for ten minutes. Geocoding intentionally uses Open-Meteo rather than public Nominatim. Public APIs can be rate-limited or temporarily unavailable; requests surface a clear error and do not silently substitute invented data.

## Model

Default: [Qwen/Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct), an open-weights 0.5B-parameter model under Apache-2.0. Configure `MODEL_ID` and `MODEL_DEVICE` in the environment. No large hosted language model is used. The deterministic scoring layer continues to return evidence and practical advice if local model loading fails.

To publish a public model repository containing the selected base weights plus this project's model card and config:

1. Install this project and run `hf auth login` with your Hugging Face account.
2. Run `python scripts/publish_model.py YOUR-HF-USERNAME/fieldnote-geoai-slm`.
3. Set `MODEL_ID=YOUR-HF-USERNAME/fieldnote-geoai-slm` for the app.

This copies the declared base weights into your public repository; it may take several minutes and requires enough local disk space. It does not fine-tune the model. You own the account, repository, and publication.

## HTTP deployment

Build and run the included Docker image, or deploy this folder to a Python container service that supports an ASGI command. Set the start command to:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set `MODEL_ID` to your published repo and persist the Hugging Face model cache if the platform supports volumes. Add authentication, request limits, monitoring, and an HTTPS domain before exposing a public endpoint. Add the final endpoint URL below before submitting:

```
API endpoint: <your deployed HTTPS URL>/api/recommend
```

No endpoint is currently deployed. No account token is included in this repository.

## Supported activities

Running/jogging, cycling, golf, cricket, outdoor football, outdoor tennis, hiking/nature walks, picnics/park outings, outdoor events/gatherings, and outdoor photography.

## Limits to disclose

- OSM availability and tags vary by place; an area-level forecast is used when no matching venue is mapped.
- Weather and air-quality grids are forecasts, not sensors at the venue. The app does not claim real-time traffic or diagnose health risks.
- The search-radius and location parser handles common phrasing; malformed or ambiguous requests should be clarified.
- Venue access, opening hours, route safety, and local restrictions are not verified.
- The current prototype evaluates the top four mapped candidate venues and a 72-hour forecast horizon.
- Forecast comfort scores are heuristic comparisons, not guarantees that conditions are safe. Users should follow local advisories and clinician guidance.

## Submission record

- Base model: Qwen/Qwen2.5-0.5B-Instruct, Apache-2.0.
- Data: Open-Meteo Geocoding, Weather Forecast, and Air Quality APIs; OpenStreetMap via Overpass API.
- Code license: MIT.
- AI coding assistance: OpenAI Codex.
- Live endpoint: not yet deployed; add the URL after hosting.
- Public Hugging Face repo: create with the included publishing script; add its URL after publishing.

