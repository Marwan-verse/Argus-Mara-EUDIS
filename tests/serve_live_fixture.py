"""Browser-test server: explicitly simulated observations, no external feed or keys."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from argus.live_server import Config, SERVICE_KEY, create_app


def main():
    with tempfile.TemporaryDirectory(prefix="argus-browser-") as directory:
        app = create_app(Config(Path(directory), label="simulated", publish_seconds=.02))

        async def seed(application):
            service = application[SERVICE_KEY]
            for mmsi, name, lon in [(999000001, "SYNTHETIC TEST", -6), (999000002, "SECOND CONTACT", -5.8)]:
                await service.accept({"recv_utc": datetime.now(timezone.utc), "msg_type": "PositionReport",
                    "mmsi": mmsi, "ship_name": name, "lat": 53, "lon": lon,
                    "sog": 0, "cog": 0, "heading": 511, "nav_status": 0, "time_utc": None,
                    "raw": "{}"})
            await service.publish()
            yield

        app.cleanup_ctx.append(seed)
        web.run_app(app, host="127.0.0.1", port=8081, access_log=None, print=None)


if __name__ == "__main__":
    main()
