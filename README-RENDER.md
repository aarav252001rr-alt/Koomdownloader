# YTMusic API - Render fix

## Replace these files
- app.py
- requirements.txt
- Dockerfile
- render.yaml

Keep `cookies.txt` in the repository root for the current setup.

## Important
Do not paste the actual API key into this README or source code.
Render generates `API_KEY` automatically from render.yaml.

## Deploy
1. Commit/push the four files and cookies.txt to GitHub.
2. Trigger a fresh Render deploy.
3. Wait for the Docker build to finish.
4. Check:
   GET /health
5. Then check diagnostics:
   GET /debug
   with header:
   X-API-Key: <your Render API_KEY>
6. Test extraction:
   curl -X GET "https://YOUR-SERVICE.onrender.com/info?url=https://music.youtube.com/watch?v=YPpwM7zfTLk" -H "X-API-Key: YOUR_API_KEY"

## Expected /debug
- yt_dlp_version should be 2026.08.19
- js_runtime.deno should be true
- cookies_file.exists should be true if cookies.txt is present

If /debug is correct but /info still fails, copy the complete Render log line beginning with
"yt-dlp extraction failed:"; that identifies the next layer of the problem.
