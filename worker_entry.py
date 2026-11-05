"""
Cloudflare Python Workers entry (WSGI).
Deploy with: uv run pywrangler deploy
"""
from workers import WorkerEntrypoint, wsgi
from app import create_app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Inject D1 + R2 bindings into Flask
        flask_app = create_app(cf_env=self.env)
        return await wsgi.fetch(flask_app, request, self.env)
