"""
Andmeallikate seisundi ja kättesaadavuse kontroll.
"""

import logging
from typing import Optional
import requests

from .config import KESKKONNAAGENTUURI_SOURCES

logger = logging.getLogger(__name__)

class HealthChecker:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()

    def check_endpoint(self, source_name: str) -> dict:
        """Kontrolli andmeallikate kättesaadavust."""
        source = KESKKONNAAGENTUURI_SOURCES.get(source_name)
        if not source:
            return {
                "source": source_name,
                "status": "unknown",
                "error": "Unknown source"
            }

        try:
            response = self.session.head(
                source.url,
                timeout=self.timeout,
                allow_redirects=True
            )
            status_code = response.status_code
            is_healthy = 200 <= status_code < 300

            return {
                "source": source_name,
                "name": source.name,
                "url": source.url,
                "status": "healthy" if is_healthy else "unhealthy",
                "status_code": status_code,
                "response_time_ms": int(response.elapsed.total_seconds() * 1000),
            }
        except requests.Timeout:
            return {
                "source": source_name,
                "name": source.name,
                "url": source.url,
                "status": "timeout",
                "error": f"Request timed out after {self.timeout}s"
            }
        except requests.RequestException as e:
            return {
                "source": source_name,
                "name": source.name,
                "url": source.url,
                "status": "error",
                "error": str(e)
            }

    def check_all(self) -> list[dict]:
        """Kontrolli kõiki andmeallikaid."""
        results = []
        for source_name in KESKKONNAAGENTUURI_SOURCES:
            result = self.check_endpoint(source_name)
            results.append(result)
            status_icon = "✓" if result["status"] == "healthy" else "✗"
            logger.info(f"{status_icon} {result.get('name', source_name)}: {result['status']}")
        return results
