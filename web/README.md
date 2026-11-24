# Grid Intelligence web

React + Vite + TypeScript + MapLibre GL + Tailwind. Talks to the FastAPI app in `../api`.

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://127.0.0.1:8000
npm run build    # static build in dist/; set VITE_API_URL to the deployed API
```

Basemap: OpenFreeMap Positron (no API key), © OpenMapTiles, data © OpenStreetMap contributors.
