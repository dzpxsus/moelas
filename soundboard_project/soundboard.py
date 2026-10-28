

"""
JESUS 2026 Soundboard
WAV sample synthesizer with octave controls and live audio effects.

Python 3.10+ recommended.

Hotkeys:
    ALT+1 ... ALT+9 = sounds 1-9
    ALT+0            = sound 10
    A W S E D F T G Y H U J K O L = synthesizer notes
    [ / ]            = lower / raise octave
"""

from __future__ import annotations

import math
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk
from math import gcd

import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput import keyboard
from PIL import Image, ImageTk
from scipy.signal import resample_poly


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_TITLE = "JESUS 2026 Soundboard"
MUSIC_DIR = "music"
PICS_DIR = "pics"
BACKGROUND_FILE = os.path.join(PICS_DIR, "background.jpg")

TARGET_DEVICE_INDEX = 17
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2
PLAYBACK_VOLUME = 0.05

WINDOW_WIDTH = 520
WINDOW_HEIGHT = 850

PRESETS = {
    "No live effects": {
        "pitch": 1.00, "echo": 0.00, "reverb": 0.00, "chorus": 0.00
    },
    "Cartoon": {
        "pitch": 1.25, "echo": 0.18, "reverb": 0.22, "chorus": 0.30
    },
    "Cinematic": {
        "pitch": 1.00, "echo": 0.38, "reverb": 0.70, "chorus": 0.08
    },
    "Studio": {
        "pitch": 1.00, "echo": 0.05, "reverb": 0.12, "chorus": 0.05
    },
    "Space": {
        "pitch": 0.85, "echo": 0.45, "reverb": 0.80, "chorus": 0.45
    },
}

TRACK_FILES = {
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


# ---------------------------------------------------------------------------
# Audio engine
# ---------------------------------------------------------------------------

class LiveAudioEngine:
    """One persistent output stream with sample-based synthesis."""

    def __init__(self, device_index: int):
        self.device_index = device_index
        self.sample_rate = TARGET_SAMPLE_RATE
        self.channels = TARGET_CHANNELS
        self.lock = threading.RLock()

        self.track = None
        self.position = 0.0
        self.track_elapsed_frames = 0
        self.params = dict(PRESETS["No live effects"])
        self.volume = PLAYBACK_VOLUME
        self.active = False

        # The last selected WAV remains available to the synthesizer.
        # MIDI note -> current sample position.
        self.synth_sample = None
        self.synth_notes = {}

        self.stream = None

        # Effect delay lines, each containing stereo frames.
        self.echo_buffer = np.zeros(
            (int(self.sample_rate * 1.2), 2), dtype=np.float32
        )
        self.reverb_a = np.zeros(
            (int(self.sample_rate * 0.071), 2), dtype=np.float32
        )
        self.reverb_b = np.zeros(
            (int(self.sample_rate * 0.113), 2), dtype=np.float32
        )
        self.chorus_buffer = np.zeros(
            (int(self.sample_rate * 0.04), 2), dtype=np.float32
        )

        self.echo_pos = 0
        self.reverb_a_pos = 0
        self.reverb_b_pos = 0
        self.chorus_pos = 0
        self.lfo_phase = 0.0
        self.echo_delay_frames = int(self.sample_rate * 0.28)

        self._open_stream()

    def _open_stream(self):
        self.stream = sd.OutputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=2048,
            latency="high",
            callback=self._callback,
        )
        self.stream.start()

    def set_params(self, **kwargs):
        with self.lock:
            for name, value in kwargs.items():
                if name in ("pitch", "echo", "reverb", "chorus"):
                    self.params[name] = float(value)

    def apply_preset(self, name):
        preset = PRESETS.get(name, PRESETS["No live effects"])
        self.set_params(**preset)

    def play(self, audio):
        with self.lock:
            self.track = audio
            self.position = 0.0
            self.track_elapsed_frames = 0
            self.active = True

            # The last WAV played becomes the synth's sample.
            self.synth_sample = audio
            self.synth_notes.clear()
            self._clear_effect_buffers()

    def stop(self):
        with self.lock:
            self.active = False
            self.track = None
            self.position = 0.0

            # Keep synth_sample loaded after STOP.
            self._clear_effect_buffers()

    def note_on(self, midi_note):
        """Play the last WAV at the selected MIDI pitch."""
        with self.lock:
            if (
                self.synth_sample is not None
                and midi_note not in self.synth_notes
            ):
                self.synth_notes[int(midi_note)] = 0.0

    def note_off(self, midi_note):
        with self.lock:
            self.synth_notes.pop(int(midi_note), None)

    def _clear_effect_buffers(self):
        self.echo_buffer.fill(0)
        self.reverb_a.fill(0)
        self.reverb_b.fill(0)
        self.chorus_buffer.fill(0)

        self.echo_pos = 0
        self.reverb_a_pos = 0
        self.reverb_b_pos = 0
        self.chorus_pos = 0
        self.lfo_phase = 0.0

    def _callback(self, outdata, frames, time_info, status):
        """
        PortAudio callback.

        Keep this function as efficient as possible. Audio callbacks must
        complete before the output buffer deadline to avoid underruns.
        """
        outdata.fill(0)

        with self.lock:
            synth = np.zeros((frames, 2), dtype=np.float32)

            # ---------------------------------------------------------------
            # Sample-based synthesizer
            # ---------------------------------------------------------------
            if self.synth_sample is not None and self.synth_notes:
                sample = self.synth_sample
                sample_length = len(sample)
                finished_notes = []

                for midi_note, position in list(self.synth_notes.items()):
                    # MIDI 60 is C4, the original sample pitch.
                    # Every semitone changes playback rate.
                    rate = 2.0 ** ((midi_note - 60) / 12.0)

                    positions = position + rate * np.arange(
                        frames, dtype=np.float64
                    )
                    valid = positions < sample_length

                    if not np.any(valid):
                        finished_notes.append(midi_note)
                        continue

                    indices = positions[valid]
                    idx0 = indices.astype(np.int64)
                    idx1 = np.minimum(idx0 + 1, sample_length - 1)
                    frac = (indices - idx0).astype(np.float32)[:, None]

                    rendered = (
                        sample[idx0] * (1.0 - frac)
                        + sample[idx1] * frac
                    )

                    # 10 ms attack fade to reduce initial clicks.
                    valid_frames = np.flatnonzero(valid)
                    elapsed_frames = position / rate + valid_frames
                    attack_frames = max(1.0, self.sample_rate * 0.010)
                    envelope = np.minimum(
                        elapsed_frames / attack_frames, 1.0
                    )
                    rendered *= envelope.astype(np.float32)[:, None]

                    synth[valid] += rendered

                    next_position = position + rate * frames

                    if next_position >= sample_length:
                        finished_notes.append(midi_note)
                    else:
                        self.synth_notes[midi_note] = next_position

                for midi_note in finished_notes:
                    self.synth_notes.pop(midi_note, None)

                note_count = max(1, len(self.synth_notes))
                synth /= max(1.0, note_count ** 0.65)

            # If no WAV is playing, synthesizer notes can still play.
            if not self.active or self.track is None:
                outdata[:] = np.tanh(synth * self.volume * 1.4)
                return

            # ---------------------------------------------------------------
            # Normal WAV playback
            # ---------------------------------------------------------------
            audio = self.track
            total_frames = len(audio)

            if total_frames == 0:
                self.active = False
                self.track = None
                outdata[:] = np.tanh(synth * self.volume * 1.4)
                return

            pitch = float(np.clip(self.params["pitch"], 0.5, 2.0))
            echo_mix = float(np.clip(self.params["echo"], 0.0, 0.8))
            reverb_mix = float(np.clip(self.params["reverb"], 0.0, 0.85))
            chorus_mix = float(np.clip(self.params["chorus"], 0.0, 0.8))

            effects_bypassed = (
                abs(pitch - 1.0) < 1e-6
                and echo_mix == 0.0
                and reverb_mix == 0.0
                and chorus_mix == 0.0
            )

            for i in range(frames):
                pos = self.position

                if pos >= total_frames:
                    self.active = False
                    self.track = None
                    break

                idx = int(pos)
                frac = pos - idx
                next_idx = min(idx + 1, total_frames - 1)

                dry = (
                    audio[idx] * (1.0 - frac)
                    + audio[next_idx] * frac
                )

                # 10 ms fade-in for WAV playback.
                attack_frames = max(1.0, self.sample_rate * 0.010)
                attack_gain = min(
                    self.track_elapsed_frames / attack_frames, 1.0
                )
                dry = dry * attack_gain
                self.track_elapsed_frames += 1
                self.position += pitch

                # Echo with feedback.
                echo_read_pos = (
                    self.echo_pos - self.echo_delay_frames
                ) % len(self.echo_buffer)
                echo_delayed = self.echo_buffer[echo_read_pos].copy()

                self.echo_buffer[self.echo_pos] = (
                    dry + echo_delayed * 0.28
                )
                self.echo_pos = (
                    self.echo_pos + 1
                ) % len(self.echo_buffer)

                # Two short feedback delay lines approximate reverb.
                ra = self.reverb_a[self.reverb_a_pos].copy()
                rb = self.reverb_b[self.reverb_b_pos].copy()

                self.reverb_a[self.reverb_a_pos] = dry + rb * 0.52
                self.reverb_b[self.reverb_b_pos] = dry + ra * 0.47

                self.reverb_a_pos = (
                    self.reverb_a_pos + 1
                ) % len(self.reverb_a)
                self.reverb_b_pos = (
                    self.reverb_b_pos + 1
                ) % len(self.reverb_b)

                reverbed = (ra + rb) * 0.5

                # Chorus with a modulated short delay.
                lfo = (math.sin(self.lfo_phase) + 1.0) * 0.5
                chorus_delay = int(
                    0.008 * self.sample_rate
                    + lfo * 0.018 * self.sample_rate
                )
                chorus_delay = min(
                    chorus_delay, len(self.chorus_buffer) - 1
                )

                read_pos = (
                    self.chorus_pos - chorus_delay
                ) % len(self.chorus_buffer)
                chorus_delayed = self.chorus_buffer[read_pos].copy()

                self.chorus_buffer[self.chorus_pos] = dry
                self.chorus_pos = (
                    self.chorus_pos + 1
                ) % len(self.chorus_buffer)

                self.lfo_phase += (
                    2.0 * math.pi * 0.7 / self.sample_rate
                )
                if self.lfo_phase >= 2.0 * math.pi:
                    self.lfo_phase -= 2.0 * math.pi

                wet = dry
                wet += echo_mix * echo_delayed
                wet += reverb_mix * reverbed
                wet += chorus_mix * (chorus_delayed - dry * 0.5)

                if effects_bypassed:
                    outdata[i] = (dry + synth[i]) * self.volume
                else:
                    outdata[i] = np.tanh(
                        wet * self.volume * 1.4
                        + synth[i] * self.volume * 1.4
                    )

    def close(self):
        self.stop()

        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

def find_output_device():
    """Prefer the configured Realtek output, then another output device."""
    try:
        devices = sd.query_devices()

        if 0 <= TARGET_DEVICE_INDEX < len(devices):
            device = devices[TARGET_DEVICE_INDEX]
            if device["max_output_channels"] >= 2:
                return TARGET_DEVICE_INDEX

        for device in devices:
            if (
                "realtek" in device["name"].lower()
                and device["max_output_channels"] >= 2
            ):
                return int(device["index"])

        default_output = sd.default.device[1]
        if default_output is not None and int(default_output) >= 0:
            return int(default_output)

    except Exception:
        pass

    return None


def load_audio(path):
    """Load WAV, convert to stereo float32, and resample to 48 kHz."""
    data, sample_rate = sf.read(
        path, dtype="float32", always_2d=True
    )

    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]

    if sample_rate != TARGET_SAMPLE_RATE:
        common = gcd(int(sample_rate), TARGET_SAMPLE_RATE)
        up = TARGET_SAMPLE_RATE // common
        down = int(sample_rate) // common

        data = resample_poly(
            data, up, down, axis=0
        ).astype(np.float32)

    return np.ascontiguousarray(data, dtype=np.float32)


# ---------------------------------------------------------------------------
# Soundboard GUI
# ---------------------------------------------------------------------------

class JesusAlarmSoundboard:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(480, 760)
        self.root.configure(bg="#111827")

        self.audio_cache = {}
        self.buttons = {}
        self.hotkey_queue = queue.Queue()
        self.listener = None
        self.device_index = find_output_device()

        try:
            self.engine = LiveAudioEngine(self.device_index)
        except Exception as exc:
            self.engine = None
            self._startup_error = str(exc)
        else:
            self._startup_error = None

        self._load_tracks()
        self._build_gui()
        self._start_hotkeys()

        self.root.after(40, self._process_hotkeys)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        if self._startup_error:
            self.status_var.set(
                "Audio unavailable: check device / sample rate"
            )
            print(
                "Could not start audio output stream:",
                self._startup_error
            )
        else:
            self.status_var.set(
                f"Ready | 48 kHz | output device {self.device_index}"
            )

    def _load_tracks(self):
        for key, (label, filename) in TRACK_FILES.items():
            path = os.path.join(MUSIC_DIR, filename)

            if not os.path.isfile(path):
                print(f"[Audio] Missing file: {path}")
                continue

            try:
                self.audio_cache[key] = {
                    "label": label,
                    "data": load_audio(path),
                    "path": path,
                }
                print(f"[Audio] Loaded: {path}")

            except Exception as exc:
                print(f"[Audio] Could not load {path}: {exc}")

    def _build_gui(self):
        self.canvas = tk.Canvas(
            self.root, bg="#111827", highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.background_photo = None

        if os.path.isfile(BACKGROUND_FILE):
            try:
                image = Image.open(BACKGROUND_FILE).convert("RGB")
                image = image.resize(
                    (WINDOW_WIDTH, WINDOW_HEIGHT),
                    Image.Resampling.LANCZOS
                )
                self.background_photo = ImageTk.PhotoImage(image)
                self.canvas.create_image(
                    0, 0, image=self.background_photo, anchor="nw"
                )
            except Exception as exc:
                print(f"[GUI] Background image unavailable: {exc}")

        frame = tk.Frame(self.canvas, bg="#111827", bd=0)
        self.canvas.create_window(
            0, 0, anchor="nw", window=frame,
            width=WINDOW_WIDTH, height=WINDOW_HEIGHT
        )

        tk.Label(
            frame,
            text="JESUS 2026 SOUNDBOARD",
            font=("Segoe UI", 16, "bold"),
            fg="#F9FAFB",
            bg="#111827"
        ).pack(pady=(12, 2))

        tk.Label(
            frame,
            text="Press a button or use ALT + number",
            font=("Segoe UI", 9),
            fg="#CBD5E1",
            bg="#111827"
        ).pack(pady=(0, 8))

        grid = tk.Frame(frame, bg="#111827")
        grid.pack(fill="x", padx=10, pady=(0, 8))

        for col in range(2):
            grid.grid_columnconfigure(col, weight=1)

        for index, key in enumerate(TRACK_FILES):
            label, _ = TRACK_FILES[key]
            loaded = key in self.audio_cache
            shortcut = "ALT+0" if key == "0" else f"ALT+{key}"
            button_text = f"{key}  {label}\n{shortcut}"

            button = tk.Button(
                grid,
                text=button_text,
                command=lambda k=key: self.play_track(k),
                font=("Segoe UI", 9, "bold"),
                fg="#F9FAFB",
                bg="#374151" if loaded else "#1F2937",
                activebackground="#4B5563",
                activeforeground="white",
                relief="flat",
                bd=0,
                padx=4,
                pady=4,
                state=(
                    "normal" if loaded and self.engine else "disabled"
                ),
                disabledforeground="#6B7280"
            )

            button.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=3,
                pady=2,
                ipady=1
            )
            self.buttons[key] = button

        # Live effects panel.
        effects = tk.LabelFrame(
            frame,
            text="LIVE EFFECTS",
            font=("Segoe UI", 9, "bold"),
            fg="#F9FAFB",
            bg="#111827",
            bd=1,
            relief="groove",
            labelanchor="n",
            padx=8,
            pady=3
        )
        effects.pack(fill="x", padx=12, pady=(0, 6))

        preset_row = tk.Frame(effects, bg="#111827")
        preset_row.pack(fill="x", pady=(0, 2))

        tk.Label(
            preset_row,
            text="Preset",
            fg="#E5E7EB",
            bg="#111827"
        ).pack(side="left")

        self.preset_var = tk.StringVar(value="No live effects")

        preset_menu = ttk.Combobox(
            preset_row,
            textvariable=self.preset_var,
            values=list(PRESETS.keys()),
            state="readonly",
            width=13
        )
        preset_menu.pack(side="right")
        preset_menu.bind(
            "<<ComboboxSelected>>", self._preset_changed
        )

        self.effect_vars = {
            "pitch": tk.DoubleVar(
                value=PRESETS["No live effects"]["pitch"]
            ),
            "echo": tk.DoubleVar(
                value=PRESETS["No live effects"]["echo"]
            ),
            "reverb": tk.DoubleVar(
                value=PRESETS["No live effects"]["reverb"]
            ),
            "chorus": tk.DoubleVar(
                value=PRESETS["No live effects"]["chorus"]
            ),
        }

        slider_specs = [
            ("Pitch", "pitch", 0.5, 2.0, "{:.2f}x"),
            ("Echo", "echo", 0.0, 0.8, "{:.2f}"),
            ("Reverb", "reverb", 0.0, 0.85, "{:.2f}"),
            ("Chorus", "chorus", 0.0, 0.8, "{:.2f}"),
        ]

        self.effect_value_labels = {}

        for label, key, minimum, maximum, fmt in slider_specs:
            row = tk.Frame(effects, bg="#111827")
            row.pack(fill="x", pady=0)

            tk.Label(
                row,
                text=label,
                width=7,
                anchor="w",
                fg="#E5E7EB",
                bg="#111827",
                font=("Segoe UI", 8)
            ).pack(side="left")

            slider = tk.Scale(
                row,
                from_=minimum,
                to=maximum,
                resolution=0.01,
                orient="horizontal",
                showvalue=False,
                variable=self.effect_vars[key],
                command=lambda value, k=key: self._effect_changed(
                    k, value
                ),
                bg="#111827",
                fg="#E5E7EB",
                troughcolor="#374151",
                highlightthickness=0,
                bd=0,
                length=245,
                sliderlength=14,
                activebackground="#60A5FA"
            )
            slider.pack(side="left", fill="x", expand=True)

            value_label = tk.Label(
                row,
                text=fmt.format(self.effect_vars[key].get()),
                width=5,
                fg="#93C5FD",
                bg="#111827",
                font=("Consolas", 8)
            )
            value_label.pack(side="right")
            self.effect_value_labels[key] = (value_label, fmt)

        controls = tk.Frame(frame, bg="#111827")
        controls.pack(fill="x", padx=12, pady=(0, 4))

        tk.Button(
            controls,
            text="STOP",
            command=self.stop_audio,
            font=("Segoe UI", 9, "bold"),
            fg="white",
            bg="#991B1B",
            activebackground="#B91C1C",
            relief="flat",
            padx=12,
            pady=3
        ).pack(side="left")

        tk.Button(
            controls,
            text="Reset effects",
            command=lambda: self.apply_preset("No live effects"),
            font=("Segoe UI", 9),
            fg="white",
            bg="#374151",
            activebackground="#4B5563",
            relief="flat",
            padx=8,
            pady=3
        ).pack(side="right")

        # QWERTY sample synthesizer.
        piano = tk.LabelFrame(
            frame,
            text="QWERTY SYNTH KEYBOARD",
            font=("Segoe UI", 9, "bold"),
            fg="#F9FAFB",
            bg="#111827",
            bd=1,
            relief="groove",
            labelanchor="n",
            padx=8,
            pady=5
        )
        piano.pack(fill="x", padx=12, pady=(0, 6))

        octave_row = tk.Frame(piano, bg="#111827")
        octave_row.pack(fill="x", pady=(0, 4))

        tk.Label(
            octave_row,
            text="Octave",
            fg="#E5E7EB",
            bg="#111827"
        ).pack(side="left")

        self.octave_var = tk.IntVar(value=4)

        tk.Button(
            octave_row,
            text="−",
            width=3,
            command=lambda: self.change_octave(-1),
            fg="white",
            bg="#374151",
            relief="flat"
        ).pack(side="right", padx=(3, 0))

        tk.Button(
            octave_row,
            text="+",
            width=3,
            command=lambda: self.change_octave(1),
            fg="white",
            bg="#374151",
            relief="flat"
        ).pack(side="right", padx=(3, 0))

        self.octave_label = tk.Label(
            octave_row,
            text="4",
            width=3,
            fg="#93C5FD",
            bg="#111827",
            font=("Segoe UI", 10, "bold")
        )
        self.octave_label.pack(side="right")

        tk.Label(
            octave_row,
            text="Shortcuts: [ / ]",
            fg="#9CA3AF",
            bg="#111827",
            font=("Segoe UI", 8)
        ).pack(side="left", padx=(12, 0))

        # Chromatic keyboard mapping.
        self.piano_key_map = {
            "a": 0, "w": 1, "s": 2, "e": 3, "d": 4,
            "f": 5, "t": 6, "g": 7, "y": 8, "h": 9,
            "u": 10, "j": 11, "k": 12, "o": 13, "l": 14,
        }

        self.pressed_piano_keys = set()
        self.held_piano_notes = {}
        self.piano_buttons = {}

        piano_keys_row = tk.Frame(piano, bg="#111827")
        piano_keys_row.pack(fill="x")

        black_semitones = {1, 3, 6, 8, 10, 13}
        key_labels = [
            "A", "W", "S", "E", "D", "F", "T", "G",
            "Y", "H", "U", "J", "K", "O", "L"
        ]

        for offset, key_name in enumerate(key_labels):
            is_black = offset in black_semitones

            key_button = tk.Button(
                piano_keys_row,
                text=key_name,
                font=("Segoe UI", 8, "bold"),
                fg="white" if is_black else "#111827",
                bg="#111827" if is_black else "#F3F4F6",
                activebackground="#60A5FA",
                relief="raised",
                bd=1,
                padx=0,
                pady=9,
                takefocus=False
            )

            key_button.pack(
                side="left", fill="x", expand=True, padx=1
            )

            key_button.bind(
                "<ButtonPress-1>",
                lambda event, k=key_name.lower(): self._piano_press(k)
            )
            key_button.bind(
                "<ButtonRelease-1>",
                lambda event, k=key_name.lower(): self._piano_release(k)
            )

            self.piano_buttons[key_name.lower()] = key_button

        tk.Label(
            piano,
            text="A W S E D F T G Y H U J K O L | Hold keys for notes",
            fg="#9CA3AF",
            bg="#111827",
            font=("Segoe UI", 8)
        ).pack(pady=(4, 0))

        self.root.bind_all(
            "<KeyPress>", self._handle_piano_keypress, add="+"
        )
        self.root.bind_all(
            "<KeyRelease>", self._handle_piano_keyrelease, add="+"
        )
        self.root.bind(
            "<FocusOut>", self._release_all_piano_keys, add="+"
        )

        self.status_var = tk.StringVar(value="Starting audio...")

        tk.Label(
            frame,
            textvariable=self.status_var,
            font=("Segoe UI", 8),
            fg="#D1D5DB",
            bg="#111827",
            wraplength=420
        ).pack(fill="x", padx=12, pady=(0, 6))

    # -----------------------------------------------------------------------
    # Synth keyboard
    # -----------------------------------------------------------------------

    def change_octave(self, amount):
        new_octave = max(
            1, min(7, self.octave_var.get() + amount)
        )
        self.octave_var.set(new_octave)
        self.octave_label.configure(text=str(new_octave))
        self.status_var.set(f"Synth octave: {new_octave}")

    def _midi_for_piano_key(self, key_name):
        # C4 is MIDI 60; each octave shifts notes by 12 semitones.
        return (
            12 * (self.octave_var.get() + 1)
            + self.piano_key_map[key_name]
        )

    def _piano_press(self, key_name):
        if key_name not in self.piano_key_map or not self.engine:
            return

        if key_name in self.pressed_piano_keys:
            return

        self.pressed_piano_keys.add(key_name)
        midi_note = self._midi_for_piano_key(key_name)
        self.held_piano_notes[key_name] = midi_note

        self.engine.note_on(midi_note)

        button = self.piano_buttons.get(key_name)
        if button:
            button.configure(relief="sunken")

    def _piano_release(self, key_name):
        if key_name not in self.piano_key_map:
            return

        self.pressed_piano_keys.discard(key_name)
        midi_note = self.held_piano_notes.pop(key_name, None)

        if self.engine and midi_note is not None:
            self.engine.note_off(midi_note)

        button = self.piano_buttons.get(key_name)
        if button:
            button.configure(relief="raised")

    def _handle_piano_keypress(self, event):
        key_name = event.keysym.lower()

        if key_name in ("bracketleft", "bracketright"):
            if key_name == "bracketleft":
                self.change_octave(-1)
            else:
                self.change_octave(1)
            return

        if key_name in self.piano_key_map:
            self._piano_press(key_name)

    def _handle_piano_keyrelease(self, event):
        key_name = event.keysym.lower()

        if key_name in self.piano_key_map:
            self._piano_release(key_name)

    def _release_all_piano_keys(self, _event=None):
        for key_name in list(self.held_piano_notes):
            self._piano_release(key_name)

    # -----------------------------------------------------------------------
    # Effects
    # -----------------------------------------------------------------------

    def _effect_changed(self, key, value):
        numeric = float(value)
        label, fmt = self.effect_value_labels[key]
        label.configure(text=fmt.format(numeric))

        if self.engine:
            self.engine.set_params(**{key: numeric})

        if hasattr(self, "preset_var"):
            self.preset_var.set("Custom")

    def _preset_changed(self, _event=None):
        self.apply_preset(self.preset_var.get())

    def apply_preset(self, name):
        if name not in PRESETS:
            name = "No live effects"

        preset = PRESETS[name]
        self.preset_var.set(name)

        for key, value in preset.items():
            self.effect_vars[key].set(value)
            label, fmt = self.effect_value_labels[key]
            label.configure(text=fmt.format(value))

        if self.engine:
            self.engine.apply_preset(name)

    # -----------------------------------------------------------------------
    # Playback
    # -----------------------------------------------------------------------

    def play_track(self, key):
        if not self.engine:
            self.status_var.set(
                "Audio engine unavailable. Check the output device."
            )
            return

        track = self.audio_cache.get(key)

        if not track:
            self.status_var.set(f"Missing audio file for sound {key}.")
            return

        self.engine.play(track["data"])
        self.status_var.set(
            f"Playing: {track['label']} | live effects: "
            f"{self.preset_var.get()}"
        )

    def stop_audio(self):
        if self.engine:
            self.engine.stop()

        self.status_var.set(
            "Stopped. The last WAV remains loaded in the synthesizer."
        )

    # -----------------------------------------------------------------------
    # Global hotkeys
    # -----------------------------------------------------------------------

    def _start_hotkeys(self):
        hotkeys = {
            f"<alt>+{key}": (
                lambda k=key: self.hotkey_queue.put(k)
            )
            for key in TRACK_FILES
        }

        self.listener = keyboard.GlobalHotKeys(hotkeys)
        self.listener.start()

    def _process_hotkeys(self):
        try:
            while True:
                key = self.hotkey_queue.get_nowait()
                self.play_track(key)
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(40, self._process_hotkeys)

    # -----------------------------------------------------------------------
    # Shutdown
    # -----------------------------------------------------------------------

    def close(self):
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass

        if self.engine:
            self.engine.close()

        self.pressed_piano_keys.clear()
        self.held_piano_notes.clear()
        self.root.destroy()


def main():
    root = tk.Tk()
    JesusAlarmSoundboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
