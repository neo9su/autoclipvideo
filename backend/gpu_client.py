"""GPU Service Client with retry and fallback support."""
import os
import time
import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Primary: SSH tunnel (localhost)
PRIMARY_URL = os.environ.get("GPU_SERVICE_URL", "http://localhost:8877")
# Fallback: Direct IP (if firewall configured)
FALLBACK_URL = os.environ.get("GPU_SERVICE_URL_FALLBACK", "http://10.190.0.203:8877")

# Retry config
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


class GpuClient:
    """GPU service client with automatic fallback."""
    
    def __init__(self):
        self.primary_url = PRIMARY_URL
        self.fallback_url = FALLBACK_URL
        self.session = requests.Session()
        self.session.timeout = 30
        
    def _request(self, method: str, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with retries."""
        for attempt in range(MAX_RETRIES):
            try:
                logger.debug(f"{method} {url} (attempt {attempt + 1})")
                resp = self.session.request(method, url, **kwargs)
                return resp
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        return None
    
    def get_health(self) -> Dict[str, Any]:
        """Check GPU service health."""
        # Try primary first
        resp = self._request("GET", f"{self.primary_url}/health")
        if resp and resp.status_code == 200:
            return resp.json()
        
        # Fallback to direct
        resp = self._request("GET", f"{self.fallback_url}/health")
        if resp and resp.status_code == 200:
            return resp.json()
        
        return {"online": False, "error": "Both endpoints failed"}
    
    def create_tts_job(self, text: str, voice_ref_id: str) -> Dict[str, Any]:
        """Submit TTS job."""
        payload = {
            "text": text,
            "voice_ref_id": voice_ref_id,
        }
        
        # Try primary
        resp = self._request("POST", f"{self.primary_url}/tts-jobs", json=payload)
        if resp and resp.status_code in (200, 201):
            return resp.json()
        
        # Fallback
        resp = self._request("POST", f"{self.fallback_url}/tts-jobs", json=payload)
        if resp and resp.status_code in (200, 201):
            return resp.json()
        
        return {"error": "Failed to submit TTS job"}
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get job status."""
        resp = self._request("GET", f"{self.primary_url}/tts-jobs/{job_id}")
        if resp and resp.status_code == 200:
            return resp.json()
        
        resp = self._request("GET", f"{self.fallback_url}/tts-jobs/{job_id}")
        if resp and resp.status_code == 200:
            return resp.json()
        
        return {"error": "Job not found"}


# Global client instance
_gpu_client = None


def get_gpu_client() -> GpuClient:
    """Get or create GPU client singleton."""
    global _gpu_client
    if _gpu_client is None:
        _gpu_client = GpuClient()
    return _gpu_client


def check_gpu_health() -> Dict[str, Any]:
    """Check GPU service health."""
    return get_gpu_client().get_health()


def submit_tts_job(text: str, voice_ref_id: str) -> Dict[str, Any]:
    """Submit TTS job."""
    return get_gpu_client().create_tts_job(text, voice_ref_id)


def get_tts_job(job_id: str) -> Dict[str, Any]:
    """Get TTS job status."""
    return get_gpu_client().get_job_status(job_id)
