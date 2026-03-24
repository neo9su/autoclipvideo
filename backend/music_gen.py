"""
Background music library generator.
Synthesises multiple looping tracks (~60s each) using numpy.
Tracks are cached in assets/music/ as _bgm_<style>.mp3.
"""
import logging
import os
import subprocess
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

MUSIC_DIR = os.path.join(os.path.dirname(__file__), "assets", "music")
_SR = 44100
_DUR = 64.0  # seconds per track

# ── Note helpers ──────────────────────────────────────────────────────────────

_NOTE_ST = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _freq(note: str) -> float:
    name, octave = note[0], int(note[1])
    return 440.0 * 2 ** ((octave - 4) * 12 + _NOTE_ST[name] - 9) / 12 * 12


def _freq(note: str) -> float:
    name, octave = note[0], int(note[1])
    s = (octave - 4) * 12 + _NOTE_ST[name] - 9
    return 440.0 * (2 ** (s / 12))


def _mix(buf: np.ndarray, tone: np.ndarray, ts: int) -> None:
    end = min(ts + len(tone), len(buf))
    if end > ts:
        buf[ts:end] += tone[: end - ts]


# ── Waveform synthesizers ─────────────────────────────────────────────────────

def _piano(freq: float, dur: float, vel: float = 0.6) -> np.ndarray:
    """Piano-like tone: harmonics + ADSR."""
    n = int(_SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    wave = (
        np.sin(2 * np.pi * freq * t) * 1.00
        + np.sin(2 * np.pi * freq * 2 * t) * 0.38
        + np.sin(2 * np.pi * freq * 3 * t) * 0.16
        + np.sin(2 * np.pi * freq * 4 * t) * 0.07
    ) / 1.61
    atk = min(int(0.012 * _SR), n)
    dcy = min(int(0.07 * _SR), n - atk)
    rel = min(int(0.20 * _SR), n)
    sus = 0.65
    env = np.full(n, sus)
    env[:atk] = np.linspace(0, 1, atk)
    env[atk: atk + dcy] = np.linspace(1, sus, dcy)
    r0 = max(atk + dcy, n - rel)
    env[r0:] = np.linspace(sus, 0, n - r0)
    return wave * env * vel


def _synth_lead(freq: float, dur: float, vel: float = 0.5) -> np.ndarray:
    """Bright synth lead: sawtooth + slight detune."""
    n = int(_SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    # Sawtooth via Fourier series (8 harmonics)
    wave = sum((-1) ** k * np.sin(2 * np.pi * freq * (k + 1) * t) / (k + 1)
               for k in range(8)) * (2 / np.pi)
    # Slight detune (chorus effect)
    wave += sum((-1) ** k * np.sin(2 * np.pi * freq * 1.005 * (k + 1) * t) / (k + 1)
                for k in range(8)) * (2 / np.pi) * 0.3
    wave /= 1.3
    atk = min(int(0.008 * _SR), n)
    rel = min(int(0.15 * _SR), n)
    env = np.ones(n)
    env[:atk] = np.linspace(0, 1, atk)
    env[max(0, n - rel):] = np.linspace(1, 0, rel)
    return wave * env * vel


def _bass_synth(freq: float, dur: float, vel: float = 0.6) -> np.ndarray:
    """Punchy sub bass: sine + square blend."""
    n = int(_SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    sine = np.sin(2 * np.pi * freq * t)
    sq = np.sign(np.sin(2 * np.pi * freq * t)) * 0.3
    wave = (sine + sq) / 1.3
    atk = min(int(0.005 * _SR), n)
    rel = min(int(0.08 * _SR), n)
    env = np.exp(-t * 4)
    env[:atk] *= np.linspace(0, 1, atk) / np.exp(-np.linspace(0, atk / _SR, atk) * 4)
    return wave * env * vel


def _pad(freq: float, dur: float, vel: float = 0.25) -> np.ndarray:
    """Soft pad: slow attack, smooth release."""
    n = int(_SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    wave = (np.sin(2 * np.pi * freq * t)
            + np.sin(2 * np.pi * freq * 2 * t) * 0.3
            + np.sin(2 * np.pi * freq * 0.5 * t) * 0.2) / 1.5
    atk = min(int(0.3 * _SR), n)
    rel = min(int(0.5 * _SR), n)
    env = np.ones(n)
    env[:atk] = np.linspace(0, 1, atk)
    env[max(0, n - rel):] = np.linspace(1, 0, min(rel, n))
    return wave * env * vel


def _kick(vel: float = 0.6) -> np.ndarray:
    dur = 0.18
    n = int(_SR * dur)
    t = np.linspace(0, dur, n)
    wave = np.sin(2 * np.pi * (160 * np.exp(-t * 35)) * t)
    env = np.exp(-t * 22)
    return wave * env * vel


def _snare(rng: np.random.Generator, vel: float = 0.35) -> np.ndarray:
    dur = 0.12
    n = int(_SR * dur)
    t = np.linspace(0, dur, n)
    tone = np.sin(2 * np.pi * 220 * t) * 0.4
    noise = rng.standard_normal(n) * 0.6
    env = np.exp(-t * 30)
    return (tone + noise) * env * vel


def _hihat(rng: np.random.Generator, dur: float = 0.03, vel: float = 0.07) -> np.ndarray:
    n = int(_SR * dur)
    t = np.linspace(0, dur, n)
    noise = rng.standard_normal(n)
    env = np.linspace(1, 0, n) ** 2
    return noise * env * vel


def _save_mp3(mix: np.ndarray, path: str) -> bool:
    """Normalise, fade, encode to mp3."""
    import soundfile as sf
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix / peak * 0.82
    fade = min(int(_SR), len(mix) // 4)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    tmp = path.replace(".mp3", "_tmp.wav")
    sf.write(tmp, mix.astype(np.float32), _SR)
    res = subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-codec:a", "libmp3lame", "-qscale:a", "2", path],
        capture_output=True,
    )
    try:
        os.remove(tmp)
    except Exception:
        pass
    return res.returncode == 0 and os.path.exists(path)


# ── Track builders ────────────────────────────────────────────────────────────

def _track_upbeat_pop(dur: float, seed: int = 1) -> np.ndarray:
    """120 BPM upbeat pop – punchy kick, snare backbeat, piano melody."""
    rng = np.random.default_rng(seed)
    bpm, beat = 120, 60.0 / 120
    bar, n = beat * 4, int(_SR * dur)
    mix = np.zeros(n)
    penta = ["C4", "D4", "E4", "G4", "A4", "C5", "D5", "E5"]
    bass_seq = ["C3", "G3", "A3", "G3", "F3", "A3", "G3", "B3"]
    chords = [["C4", "E4", "G4"], ["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"]]
    mel = [0, 2, 4, 2, 4, 6, 5, 4, 2, 0, 1, 2, 4, 5, 4, 2, 6, 5, 4, 2, 0, 1, 2, 4]
    n_beats = int(dur / beat)
    for i in range(0, n_beats, 2):
        note = bass_seq[(i // 2) % len(bass_seq)]
        _mix(mix, _piano(_freq(note), beat * 0.5, 0.45), int(i * beat * _SR))
    for i in range(n_beats):
        if i % 4 in (1, 3):
            chord = chords[(i // 4) % len(chords)]
            ts = int(i * beat * _SR)
            for note in chord:
                _mix(mix, _piano(_freq(note), beat * 0.7, 0.18), ts)
    for i in range(n_beats):
        idx = mel[i % len(mel)]
        _mix(mix, _piano(_freq(penta[min(idx, 7)]), beat * 0.65, 0.28), int(i * beat * _SR))
    for i in range(n_beats):
        if i % 4 in (0, 2):
            _mix(mix, _kick(0.55), int(i * beat * _SR))
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.32), int(i * beat * _SR))
        _mix(mix, _hihat(rng, 0.025, 0.06), int(i * beat * _SR))
    return mix


def _track_electronic(dur: float, seed: int = 2) -> np.ndarray:
    """128 BPM electronic/EDM – synth lead, four-on-the-floor kick, arpeggios."""
    rng = np.random.default_rng(seed)
    bpm, beat = 128, 60.0 / 128
    n = int(_SR * dur)
    mix = np.zeros(n)
    # A minor: A C D E G
    scale = ["A3", "C4", "D4", "E4", "G4", "A4", "C5", "D5"]
    arp_pattern = [0, 2, 4, 5, 4, 2, 3, 5, 4, 2, 0, 1, 2, 4, 5, 4]
    bass_notes = ["A2", "E2", "F2", "G2"]
    n_beats = int(dur / beat)
    # Four-on-the-floor kick
    for i in range(n_beats):
        _mix(mix, _kick(0.60), int(i * beat * _SR))
    # Snare on 2 and 4
    for i in range(n_beats):
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.28), int(i * beat * _SR))
    # 16th hi-hats
    for i in range(n_beats * 4):
        _mix(mix, _hihat(rng, 0.018, 0.045), int(i * (beat / 4) * _SR))
    # Bass
    for i in range(0, n_beats, 4):
        note = bass_notes[(i // 4) % 4]
        _mix(mix, _bass_synth(_freq(note), beat * 4 * 0.8, 0.55), int(i * beat * _SR))
    # Arp melody (16th notes)
    for i in range(n_beats * 4):
        if i % 2 != 0:
            continue
        idx = arp_pattern[i % len(arp_pattern)]
        _mix(mix, _synth_lead(_freq(scale[min(idx, 7)]), beat * 0.45, 0.22),
             int(i * (beat / 4) * _SR))
    # Pad chords every 2 bars
    pad_chords = [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"], ["E3", "G3", "B3"]]
    for i in range(int(dur / (beat * 8))):
        chord = pad_chords[i % len(pad_chords)]
        ts = int(i * beat * 8 * _SR)
        for note in chord:
            _mix(mix, _pad(_freq(note), beat * 8, 0.18), ts)
    return mix


def _track_cute_pop(dur: float, seed: int = 3) -> np.ndarray:
    """110 BPM cute/kawaii – bright piano melody, light percussion, sparkle."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / 110
    n = int(_SR * dur)
    mix = np.zeros(n)
    # D major pentatonic: D E F# A B
    penta = ["D4", "E4", "F4", "A4", "B4", "D5", "E5", "F5"]  # simplified
    chords = [["D4", "F4", "A4"], ["B3", "D4", "F4"], ["G3", "B3", "D4"], ["A3", "C4", "E4"]]
    bass_seq = ["D3", "A3", "B3", "G3", "A3", "D3", "G3", "A3"]
    mel = [0, 1, 2, 4, 5, 4, 2, 1, 0, 2, 4, 5, 7, 6, 5, 4, 2, 0, 1, 2, 4, 2, 0, 1]
    n_beats = int(dur / beat)
    # Bass every beat
    for i in range(n_beats):
        note = bass_seq[(i // 2) % len(bass_seq)]
        _mix(mix, _piano(_freq(note), beat * 0.45, 0.38), int(i * beat * _SR))
    # Chord stabs on beat 1 and 3
    for i in range(n_beats):
        if i % 4 in (0, 2):
            chord = chords[(i // 4) % len(chords)]
            ts = int(i * beat * _SR)
            for note in chord:
                _mix(mix, _piano(_freq(note), beat * 0.55, 0.17), ts)
    # Sparkly melody (8th notes)
    for i in range(n_beats * 2):
        idx = mel[(i // 1) % len(mel)]
        _mix(mix, _piano(_freq(penta[min(idx, 7)]), beat * 0.4, 0.30),
             int(i * (beat / 2) * _SR))
    # Light kick on 1 and 3
    for i in range(n_beats):
        if i % 4 in (0, 2):
            _mix(mix, _kick(0.42), int(i * beat * _SR))
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.22), int(i * beat * _SR))
        _mix(mix, _hihat(rng, 0.020, 0.05), int(i * beat * _SR))
        if i % 2 == 1:
            _mix(mix, _hihat(rng, 0.015, 0.03), int(i * beat * _SR))
    return mix


def _track_chill_lofi(dur: float, seed: int = 4) -> np.ndarray:
    """90 BPM lo-fi chill – soft piano, laid-back rhythm, warm pads."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / 90
    n = int(_SR * dur)
    mix = np.zeros(n)
    # F major: F G A C D
    penta = ["F3", "G3", "A3", "C4", "D4", "F4", "G4", "A4"]
    chords = [["F3", "A3", "C4"], ["D3", "F3", "A3"], ["C3", "E3", "G3"], ["G3", "B3", "D4"]]
    mel = [4, 5, 4, 2, 0, 1, 2, 4, 5, 7, 6, 5, 4, 2, 4, 5, 4, 2, 0, 2, 4, 5, 4, 2]
    n_beats = int(dur / beat)
    # Warm pads (4 bars each)
    for i in range(int(dur / (beat * 4))):
        chord = chords[i % len(chords)]
        ts = int(i * beat * 4 * _SR)
        for note in chord:
            _mix(mix, _pad(_freq(note), beat * 4, 0.22), ts)
    # Bass (half notes, lazy)
    bass_seq = ["F2", "D2", "C2", "G2"]
    for i in range(0, n_beats, 2):
        note = bass_seq[(i // 4) % len(bass_seq)]
        _mix(mix, _piano(_freq(note), beat * 1.8, 0.35), int(i * beat * _SR))
    # Melody (quarter notes)
    for i in range(n_beats):
        idx = mel[i % len(mel)]
        _mix(mix, _piano(_freq(penta[min(idx, 7)]), beat * 0.75, 0.25), int(i * beat * _SR))
    # Laid-back kick (slightly off-beat feel)
    kick_offsets = [0, 0, 0, 0.05, 0, 0, 0.03, 0]
    for i in range(n_beats):
        if i % 4 in (0, 2):
            off = kick_offsets[i % len(kick_offsets)]
            ts = int((i * beat + off) * _SR)
            _mix(mix, _kick(0.45), ts)
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.25), int(i * beat * _SR))
        _mix(mix, _hihat(rng, 0.030, 0.04), int(i * beat * _SR))
    return mix


def _track_energetic(dur: float, seed: int = 5) -> np.ndarray:
    """138 BPM high-energy – driving synth bass, fast hi-hats, bright lead."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / 138
    n = int(_SR * dur)
    mix = np.zeros(n)
    # G major pentatonic: G A B D E
    penta = ["G4", "A4", "B4", "D5", "E5", "G5", "A5", "B5"]
    bass_seq = ["G2", "D2", "E2", "C2", "G2", "A2", "D2", "E2"]
    mel = [0, 2, 4, 5, 4, 2, 0, 4, 5, 7, 5, 4, 2, 4, 5, 4, 0, 2, 3, 4, 5, 4, 2, 0]
    n_beats = int(dur / beat)
    # Four-on-the-floor kick
    for i in range(n_beats):
        _mix(mix, _kick(0.65), int(i * beat * _SR))
    # Snare on 2 and 4
    for i in range(n_beats):
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.35), int(i * beat * _SR))
    # Fast 16th hi-hats with open hat on offbeat
    for i in range(n_beats * 4):
        dur_hat = 0.040 if i % 8 == 4 else 0.018  # open hat
        vol_hat = 0.10 if i % 8 == 4 else 0.055
        _mix(mix, _hihat(rng, dur_hat, vol_hat), int(i * (beat / 4) * _SR))
    # Synth bass (8th notes)
    for i in range(n_beats * 2):
        note = bass_seq[(i // 2) % len(bass_seq)]
        _mix(mix, _bass_synth(_freq(note), beat * 0.45, 0.52),
             int(i * (beat / 2) * _SR))
    # Synth lead melody
    for i in range(n_beats):
        idx = mel[i % len(mel)]
        _mix(mix, _synth_lead(_freq(penta[min(idx, 7)]), beat * 0.65, 0.25),
             int(i * beat * _SR))
    return mix


def _track_funky(dur: float, seed: int = 6) -> np.ndarray:
    """105 BPM funky groove – slap bass feel, staccato chords, syncopated melody."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / 105
    n = int(_SR * dur)
    mix = np.zeros(n)
    # C major: C D E F G A
    scale = ["C4", "D4", "E4", "F4", "G4", "A4", "C5", "D5"]
    chords = [["C4", "E4", "G4"], ["F3", "A3", "C4"], ["G3", "B3", "D4"], ["A3", "C4", "E4"]]
    bass_seq = ["C3", "G3", "C3", "F2", "G2", "C3", "A2", "G2"]
    mel = [0, 2, 4, 2, 5, 4, 2, 4, 6, 5, 4, 2, 4, 5, 6, 5, 4, 2, 0, 2, 4, 6, 5, 4]
    n_beats = int(dur / beat)
    # Funky bass (16th note groove)
    for i in range(n_beats * 4):
        if i % 16 in (0, 3, 6, 8, 11, 14):  # syncopated pattern
            note = bass_seq[(i // 8) % len(bass_seq)]
            _mix(mix, _bass_synth(_freq(note), beat * 0.22, 0.50),
                 int(i * (beat / 4) * _SR))
    # Staccato chord stabs
    for i in range(n_beats * 4):
        if i % 8 in (2, 5, 7):
            chord = chords[(i // 16) % len(chords)]
            ts = int(i * (beat / 4) * _SR)
            for note in chord:
                _mix(mix, _piano(_freq(note), beat * 0.18, 0.22), ts)
    # Melody
    for i in range(n_beats):
        idx = mel[i % len(mel)]
        _mix(mix, _piano(_freq(scale[min(idx, 7)]), beat * 0.55, 0.28),
             int(i * beat * _SR))
    # Drums
    for i in range(n_beats):
        if i % 4 == 0:
            _mix(mix, _kick(0.58), int(i * beat * _SR))
        if i % 4 * 4 + 2 < n_beats * 4:
            _mix(mix, _kick(0.38), int((i * 4 + 2) * (beat / 4) * _SR))  # ghost kick
        if i % 4 in (1, 3):
            _mix(mix, _snare(rng, 0.32), int(i * beat * _SR))
        _mix(mix, _hihat(rng, 0.020, 0.055), int(i * beat * _SR))
        _mix(mix, _hihat(rng, 0.015, 0.035), int((i + 0.5) * beat * _SR))
    return mix


# ── Public API ────────────────────────────────────────────────────────────────

_TRACKS = [
    ("_bgm_upbeat_pop",   _track_upbeat_pop,  "120 BPM upbeat pop"),
    ("_bgm_electronic",   _track_electronic,  "128 BPM electronic EDM"),
    ("_bgm_cute_pop",     _track_cute_pop,    "110 BPM cute kawaii pop"),
    ("_bgm_chill_lofi",   _track_chill_lofi,  "90 BPM chill lo-fi"),
    ("_bgm_energetic",    _track_energetic,   "138 BPM high-energy"),
    ("_bgm_funky",        _track_funky,       "105 BPM funky groove"),
]


def generate_track(name: str, builder, label: str) -> Optional[str]:
    """Generate a single track and save to MUSIC_DIR."""
    try:
        import soundfile  # noqa – check availability
    except ImportError:
        logger.warning("soundfile not installed – cannot generate BGM")
        return None
    os.makedirs(MUSIC_DIR, exist_ok=True)
    path = os.path.join(MUSIC_DIR, name + ".mp3")
    logger.info(f"Generating {label} → {os.path.basename(path)} …")
    mix = builder(_DUR)
    if _save_mp3(mix, path):
        sz = os.path.getsize(path) // 1024
        logger.info(f"  ✓ {os.path.basename(path)} ({sz} KB)")
        return path
    logger.error(f"  ✗ Failed to save {path}")
    return None


def generate_library(force: bool = False) -> list[str]:
    """
    Generate all tracks that don't already exist.
    Pass force=True to regenerate even if cached.
    Returns list of generated/existing paths.
    """
    results = []
    for name, builder, label in _TRACKS:
        path = os.path.join(MUSIC_DIR, name + ".mp3")
        if not force and os.path.exists(path):
            results.append(path)
            logger.info(f"Cached: {os.path.basename(path)}")
            continue
        p = generate_track(name, builder, label)
        if p:
            results.append(p)
    return results


def generate_bgm(duration: float = _DUR) -> Optional[str]:
    """
    Generate (or return cached) the default upbeat-pop BGM.
    Used as fallback when no user music exists.
    """
    path = os.path.join(MUSIC_DIR, "_bgm_upbeat_pop.mp3")
    if os.path.exists(path):
        return path
    return generate_track("_bgm_upbeat_pop", _track_upbeat_pop, "120 BPM upbeat pop")


if __name__ == "__main__":
    import logging as _log
    _log.basicConfig(level=_log.INFO, format="%(message)s")
    print(f"Generating music library in {MUSIC_DIR} …\n")
    paths = generate_library(force=True)
    print(f"\nDone: {len(paths)} tracks generated.")
