# digital_twin_me
Interact with my Digital Twin

## Docker (cloud server)

Set `CLOUD_SERVER_IP` in `.env` to your server’s public IP or hostname (used for a startup URL hint). The app listens on `0.0.0.0:7860` inside the container.

```bash
docker build -t digital-twin-me .
docker run --rm -p 7860:7860 --env-file .env digital-twin-me
```

Ensure `me/linkedin.pdf` and `me/summary.txt` exist on the host before build (they are copied into the image).
