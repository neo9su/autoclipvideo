"""
Voice isolation via spectral noise reduction (noisereduce).
Falls back to ffmpeg-only filtering if noisereduce unavailable.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_NR_AVAILABLE: bool | None = None


def _check_nr() -> bool:
    global _NR_AVAILABLE
    if _NR_AVAILABLE is None:
        try:
            import noisereduce  # noqa
            import soundfile    # noqa
            import numpy        # noqa
            _NR_AVAILABLE = True
        except ImportError:
            _NR_AVAILABLE = False
    return _NR_AVAILABLE


async def extract_and_denoise(
    mp4: str,
    ss: float,       # seek position in mp4
    duration: float, # how many seconds to extract
    out_wav: str,
) -> bool:
    """
    Extract `duration` seconds of audio starting at `ss` from `mp4`,
    apply non-stationary spectral noise reduction, and save to `out_wav`.
    Returns True on success.
    """
    if not _check_nr():
        return False

    import noisereduce as nr
    import soundfile as sf
    import numpy as np

    raw_wav = out_wav + ".raw.wav"
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{ss:.3f}", "-t", f"{duration:.3f}", "-i", mp4,
        "-vn", "-ar", "44100", "-ac", "1", "-acodec", "pcm_s16le",
        raw_wav,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(raw_wav):
        return False

    try:
        data, rate = sf.read(raw_wav)
        # Non-stationary mode adapts to time-varying noise (hair dryer, wind, etc.)
        reduced = nr.reduce_noise(
            y=data,
            sr=rate,
            stationary=False,
            prop_decrease=0.75,   # 75 % noise suppression – preserves voice energy
            n_fft=1024,
            time_constant_s=2.0,  # noise estimate time constant
        )
        # Gentle high-pass to cut sub-100 Hz rumble
        from scipy.signal import butter, sosfilt
        sos = butter(4, 100.0 / (rate / 2), btype="high", output="sos")
        reduced = sosfilt(sos, reduced).astype(np.float32)
        # Normalise peak to -1 dBFS so voice isn't lost after mixing
        peak = np.max(np.abs(reduced))
        if peak > 0:
            reduced = (reduced / peak * 0.89).astype(np.float32)
        sf.write(out_wav, reduced, rate)
        return True
    except Exception as e:
        logger.warning(f"noisereduce failed: {e}")
        return False
    finally:
        try:
            os.remove(raw_wav)
        except Exception:
            pass
