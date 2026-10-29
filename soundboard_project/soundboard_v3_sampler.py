
"""
JESUS 2026 SOUNDBOARD 3.0
WAV soundboard + polyphonic synthesizer + WAV sampler + performance looper.

Requirements:
    python -m pip install --user numpy scipy sounddevice soundfile pynput Pillow

Optional drag-and-drop support:
    tkinterdnd2

Folder structure:
    soundboard.py
    music/
    pics/

Shortcuts:
    ALT+1 ... ALT+9 = play WAV files
    ALT+0 = play WAV file 10
    A W S E D F T G Y H U J K O L = synthesizer notes
    [ / ] = lower / raise octave
    SPACE = stop WAV playback
    REC / PLAY LOOP = record and loop performances
"""

import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard
from PIL import Image, ImageTk
from scipy.signal import lfilter, resample_poly


# ============================================================
# CONFIGURATION
# ============================================================

APP_TITLE = "JESUS 2026 Soundboard 3.0"

MUSIC_DIR = "music"
PICS_DIR = "pics"
BACKGROUND_FILE = os.path.join(PICS_DIR, "background.jpg")

PREFERRED_DEVICE = 17
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 2048

WAV_VOLUME = 0.65
SYNTH_VOLUME = 0.20
MASTER_VOLUME = 0.75

MAX_VOICES = 8

TRACKS = {
    "1": ("Tarzan", "tarzan.wav"),
    "2": ("Bip Bip", "bipbip.wav"),
    "3": ("Badum Tss", "badumtss.wav"),
    "4": ("R2-D2", "r2D2.wav"),
    "5": ("Scout", "scout.wav"),
    "6": ("Batman", "batman.wav"),
    "7": ("Sound 7", "sound7.wav"),
    "8": ("Sound 8", "sound8.wav"),
    "9": ("Sound 9", "sound9.wav"),
    "0": ("Sound 10", "sound10.wav"),
}

KEY_SEMITONES = {
    "a": 0, "w": 1,
    "s": 2, "e": 3,
    "d": 4, "f": 5,
    "t": 6, "g": 7,
    "y": 8, "h": 9,
    "u": 10, "j": 11,
    "k": 12, "o": 13, "l": 14,
}


# ============================================================
# AUDIO DEVICE
# ============================================================

def find_output_device():
    """Choose the preferred output if available, otherwise the default."""
    try:
        devices = sd.query_devices()

        if 0 <= PREFERRED_DEVICE < len(devices):
            candidate = devices[PREFERRED_DEVICE]
            if candidate["max_output_channels"] >= 2:
                print("[Audio] Preferred output:", candidate["name"])
                return PREFERRED_DEVICE

        default_device = sd.default.device[1]
        if default_device is not None and int(default_device) >= 0:
            device = sd.query_devices(int(default_device))
            if device["max_output_channels"] >= 2:
                print("[Audio] Default output:", device["name"])
                return int(default_device)

        for index, device in enumerate(devices):
            if device["max_output_channels"] >= 2:
                print("[Audio] Using output:", device["name"])
                return index

    except Exception as exc:
        print("[Audio] Device discovery error:", exc)

    return None


def load_wav(path):
    """Load WAV data and convert it to 48 kHz stereo float audio."""
    audio, rate = sf.read(
        path,
        dtype="float32",
        always_2d=True
    )

    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    if rate != SAMPLE_RATE:
        common = math.gcd(int(rate), SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // common,
            int(rate) // common,
            axis=0
        ).astype(np.float32)

    audio = np.nan_to_num(audio, copy=False)
    return np.ascontiguousarray(audio, dtype=np.float32)


# ============================================================
# SYNTH VOICE
# ============================================================

class SynthVoice:
    """One oscillator voice with an ADSR envelope."""

    def __init__(self, midi_note, waveform, velocity, phase=0.0):
        self.note = int(midi_note)
        self.waveform = waveform
        self.velocity = float(velocity)
        self.phase = float(phase)

        self.stage = "attack"
        self.stage_position = 0
        self.level = 0.0
        self.release_start = 0.0

    def release(self):
        if self.stage != "release":
            self.release_start = self.level
            self.stage = "release"
            self.stage_position = 0

    def render_envelope(
        self, frames, rate, attack, decay, sustain, release
    ):
        """Generate a click-reducing envelope without a per-sample loop."""
        envelope = np.zeros(frames, dtype=np.float32)
        offset = 0

        attack_n = max(1, int(attack * rate))
        decay_n = max(1, int(decay * rate))
        release_n = max(1, int(release * rate))

        while offset < frames:
            remaining = frames - offset

            if self.stage == "attack":
                count = min(
                    remaining,
                    attack_n - self.stage_position
                )
                positions = (
                    self.stage_position
                    + np.arange(count, dtype=np.float32)
                    + 1.0
                )
                envelope[offset:offset + count] = np.minimum(
                    positions / attack_n, 1.0
                )
                self.stage_position += count
                self.level = min(
                    self.stage_position / attack_n, 1.0
                )

                if self.stage_position >= attack_n:
                    self.stage = "decay"
                    self.stage_position = 0
                    self.level = 1.0

            elif self.stage == "decay":
                count = min(
                    remaining,
                    decay_n - self.stage_position
                )
                positions = (
                    self.stage_position
                    + np.arange(count, dtype=np.float32)
                    + 1.0
                )
                progress = np.minimum(positions / decay_n, 1.0)
                values = 1.0 + (sustain - 1.0) * progress

                envelope[offset:offset + count] = values
                self.stage_position += count
                self.level = float(values[-1])

                if self.stage_position >= decay_n:
                    self.stage = "sustain"
                    self.stage_position = 0
                    self.level = sustain

            elif self.stage == "sustain":
                count = remaining
                envelope[offset:offset + count] = sustain
                self.level = sustain

            elif self.stage == "release":
                count = min(
                    remaining,
                    release_n - self.stage_position
                )
                positions = (
                    self.stage_position
                    + np.arange(count, dtype=np.float32)
                    + 1.0
                )
                progress = np.minimum(positions / release_n, 1.0)
                values = self.release_start * (1.0 - progress)

                envelope[offset:offset + count] = values
                self.stage_position += count
                self.level = max(float(values[-1]), 0.0)

                if self.stage_position >= release_n:
                    self.stage = "finished"
                    self.level = 0.0

            else:
                break

            offset += count

        return envelope
