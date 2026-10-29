

import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, messagebox

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

APP_TITLE = "JESUS 2026 Soundboard 2.0"

MUSIC_DIR = "music"
PICS_DIR = "pics"
BACKGROUND_FILE = os.path.join(PICS_DIR, "background.jpg")

PREFERRED_DEVICE = 17
SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK_SIZE = 2048

# Independent volume controls
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

# QWERTY chromatic keyboard. A = root note.
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
                print(
                    "[Audio] Preferred output:",
                    candidate["name"]
                )
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

    # Remove invalid values that could cause audio glitches.
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

    def render_envelope(self, frames, rate, attack, decay,
                        sustain, release):
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


# ============================================================
# AUDIO ENGINE
# ============================================================

class AudioEngine:
    """
    Single persistent output stream.

    WAV playback and the synthesizer are separate sources and can
    be mixed together. The callback processes blocks rather than
    opening a new stream for every note.
    """

    def __init__(self, device):
        self.device = device
        self.lock = threading.RLock()

        self.wav_audio = None
        self.wav_position = 0.0
        self.wav_active = False
        self.wav_fade_in_position = 0

        self.voices = {}
        self.sample_audio = None
        self.sample_name = ""
        self.sample_mode = False
        self.sample_voices = {}
        self.waveform = "Saw"
        self.attack = 0.010
        self.decay = 0.12
        self.sustain = 0.70
        self.release = 0.080

        self.cutoff = 12000.0
        self.resonance = 0.0
        self.detune = 0.0
        self.sub_level = 0.0

        self.synth_volume = SYNTH_VOLUME
        self.wav_volume = WAV_VOLUME
        self.master_volume = MASTER_VOLUME

        # Simple stereo delay and reverb buffers.
        self.delay_mix = 0.0
        self.reverb_mix = 0.0
        self.delay_seconds = 0.28

        self.delay_buffer = np.zeros(
            (int(SAMPLE_RATE * 1.5), 2), dtype=np.float32
        )
        self.reverb_buffer = np.zeros(
            (int(SAMPLE_RATE * 0.13), 2), dtype=np.float32
        )
        self.delay_position = 0
        self.reverb_position = 0

        # One-pole low-pass filter state.
        self.filter_state = np.zeros((1, 2), dtype=np.float32)

        self.stream = sd.OutputStream(
            device=device,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            latency="high",
            callback=self.callback
        )
        self.stream.start()

        print(
            f"[Audio] Running at {SAMPLE_RATE} Hz, "
            f"block size {BLOCK_SIZE}"
        )

    # --------------------------------------------------------
    # WAV PLAYER
    # --------------------------------------------------------

    def play_wav(self, audio):
        with self.lock:
            self.wav_audio = audio
            self.wav_position = 0.0
            self.wav_fade_in_position = 0
            self.wav_active = True

    def stop_wav(self):
        with self.lock:
            self.wav_active = False
            self.wav_audio = None
            self.wav_position = 0.0

    # --------------------------------------------------------
    # WAV SAMPLER / PERFORMANCE RECORDER
    # --------------------------------------------------------

    def choose_sample(self):
        path = filedialog.askopenfilename(
            title="Choose a WAV sample",
            filetypes=[("WAV audio", "*.wav"), ("Audio files", "*.wav *.flac *.ogg *.aiff"), ("All files", "*.*")]
        )
        if path:
            self.load_sampler_file(path)

    def drop_sample(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
            if paths:
                self.load_sampler_file(paths[0])
        except Exception as exc:
            messagebox.showerror("Sampler", f"Could not read dropped file.\\n{exc}")

    def load_sampler_file(self, path):
        if not self.engine:
            self.status.set("Audio engine is unavailable.")
            return
        try:
            audio = load_wav(path)
            if len(audio) < 2:
                raise ValueError("The audio file is empty.")
            self.engine.load_sample(audio, os.path.basename(path))
            self.sample_path = path
            self.sample_label.configure(text=f"Sampler: {os.path.basename(path)}")
            self.status.set("Sampler mode: keyboard plays the loaded WAV at different pitches.")
        except Exception as exc:
            messagebox.showerror("Could not load sample", str(exc))

    def switch_to_synth(self):
        if self.engine:
            self.engine.use_synth_mode()
        self.sample_label.configure(text="Sampler off: built-in oscillator synthesizer")
        self.status.set("Synth mode restored.")

    def toggle_recording(self):
        if not self.recording:
            self.stop_loop()
            self.recorded_events = []
            self.record_start = time.monotonic()
            self.recording = True
            self.record_button.configure(text="■ STOP REC", bg="#7F1D1D")
            self.status.set("Recording performance... play the keyboard.")
        else:
            self.recording = False
            self.record_button.configure(text="● REC", bg="#B91C1C")
            if self.recorded_events:
                last_time = max(event[0] for event in self.recorded_events)
                self.loop_duration = max(last_time + 0.25, 0.5)
                self.status.set(f"Recording saved in memory: {len(self.recorded_events)} note events.")
            else:
                self.loop_duration = 0.0
                self.status.set("Recording stopped: no notes captured.")

    def record_note_event(self, kind, note):
        if self.recording:
            self.recorded_events.append((time.monotonic() - self.record_start, kind, int(note)))

    def play_loop(self):
        if not self.recorded_events:
            self.status.set("Nothing recorded yet. Press REC, play notes, then stop recording.")
            return
        self.stop_loop()
        self.looping = True
        self.loop_duration = max(
            self.loop_duration,
            max(event[0] for event in self.recorded_events) + 0.25,
            0.5
        )
        self._schedule_loop_pass(0.0)
        self.status.set("Playing recorded performance in a loop.")

    def _schedule_loop_pass(self, offset):
        if not self.looping:
            return
        for event_time, kind, note in self.recorded_events:
            delay_ms = max(0, int(event_time * 1000))
            callback = lambda k=kind, n=note: self._play_recorded_event(k, n)
            self.loop_after_ids.append(self.root.after(delay_ms, callback))
        delay_ms = max(1, int(self.loop_duration * 1000))
        self.loop_after_ids.append(
            self.root.after(delay_ms, lambda: self._schedule_loop_pass(0.0))
        )

    def _play_recorded_event(self, kind, note):
        if not self.looping or not self.engine:
            return
        if kind == "on":
            self.engine.note_on(note)
        else:
            self.engine.note_off(note)

    def stop_loop(self):
        self.looping = False
        for after_id in self.loop_after_ids:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self.loop_after_ids.clear()
        if self.engine:
            self.engine.release_all()

    # --------------------------------------------------------
    # SYNTH CONTROLS
    # --------------------------------------------------------

    def set_waveform(self, waveform):
        with self.lock:
            self.waveform = waveform

    def set_envelope(self, attack=None, decay=None,
                     sustain=None, release=None):
        with self.lock:
            if attack is not None:
                self.attack = float(attack)
            if decay is not None:
                self.decay = float(decay)
            if sustain is not None:
                self.sustain = float(sustain)
            if release is not None:
                self.release = float(release)

    def set_filter(self, cutoff=None, resonance=None):
        with self.lock:
            if cutoff is not None:
                self.cutoff = float(cutoff)
            if resonance is not None:
                self.resonance = float(resonance)

    def set_effects(self, delay=None, reverb=None):
        with self.lock:
            if delay is not None:
                self.delay_mix = float(delay)
            if reverb is not None:
                self.reverb_mix = float(reverb)

    def set_detune(self, value):
        with self.lock:
            self.detune = float(value)

    def set_sub_level(self, value):
        with self.lock:
            self.sub_level = float(value)

    def load_sample(self, audio, name="sample"):
        with self.lock:
            self.sample_audio = audio
            self.sample_name = name
            self.sample_mode = True
            self.sample_voices.clear()
            self.voices.clear()

    def use_synth_mode(self):
        with self.lock:
            self.sample_mode = False
            self.sample_voices.clear()

    def note_on(self, midi_note, velocity=0.8):
        with self.lock:
            midi_note = int(midi_note)

            if self.sample_mode and self.sample_audio is not None:
                self.sample_voices.pop(midi_note, None)
                if len(self.sample_voices) >= MAX_VOICES:
                    oldest = next(iter(self.sample_voices))
                    del self.sample_voices[oldest]
                self.sample_voices[midi_note] = {
                    "position": 0.0,
                    "ratio": 2.0 ** ((midi_note - 60) / 12.0),
                    "velocity": float(velocity),
                    "release_remaining": 0,
                    "release_total": max(1, int(0.04 * SAMPLE_RATE)),
                    "release_gain": 1.0,
                }
                return

            # Retriggering an existing note replaces that voice.
            if midi_note in self.voices:
                del self.voices[midi_note]

            # Eight-note polyphony, dropping the oldest voice.
            if len(self.voices) >= MAX_VOICES:
                oldest = next(iter(self.voices))
                del self.voices[oldest]

            self.voices[midi_note] = SynthVoice(
                midi_note,
                self.waveform,
                velocity
            )

    def note_off(self, midi_note):
        with self.lock:
            midi_note = int(midi_note)
            if self.sample_mode:
                voice = self.sample_voices.get(midi_note)
                if voice and voice["release_remaining"] <= 0:
                    voice["release_remaining"] = voice["release_total"]
                    voice["release_gain"] = 1.0
                return
            voice = self.voices.get(midi_note)
            if voice:
                voice.release()

    def release_all(self):
        with self.lock:
            for voice in self.voices.values():
                voice.release()
            for voice in self.sample_voices.values():
                if voice["release_remaining"] <= 0:
                    voice["release_remaining"] = voice["release_total"]
                    voice["release_gain"] = 1.0

    # --------------------------------------------------------
    # OSCILLATORS
    # --------------------------------------------------------

    @staticmethod
    def oscillator(phase, waveform):
        if waveform == "Sine":
            return np.sin(phase)

        if waveform == "Square":
            return np.where(
                np.sin(phase) >= 0.0, 1.0, -1.0
            )

        if waveform == "Triangle":
            return (2.0 / math.pi) * np.arcsin(np.sin(phase))

        # Sawtooth, using phase wrapped into one cycle.
        cycle = phase / (2.0 * math.pi)
        return 2.0 * (cycle - np.floor(cycle + 0.5))

    def render_synth(self, frames):
        result = np.zeros((frames, 2), dtype=np.float32)
        finished = []

        for midi_note, voice in list(self.voices.items()):
            frequency = 440.0 * (
                2.0 ** ((midi_note - 69) / 12.0)
            )

            # Slight oscillator detune creates a thicker sound.
            frequency_a = frequency
            frequency_b = frequency * (
                2.0 ** (self.detune / 1200.0)
            )

            steps = np.arange(frames, dtype=np.float64)

            phase_a = voice.phase + (
                2.0 * math.pi * frequency_a / SAMPLE_RATE
            ) * steps

            phase_b = voice.phase + (
                2.0 * math.pi * frequency_b / SAMPLE_RATE
            ) * steps

            wave_a = self.oscillator(
                phase_a, voice.waveform
            ).astype(np.float32)

            wave_b = self.oscillator(
                phase_b, voice.waveform
            ).astype(np.float32)

            # Blend two oscillators. Optional sub oscillator is one
            # octave below the played note.
            mono = 0.55 * wave_a + 0.45 * wave_b

            if self.sub_level > 0.0:
                phase_sub = voice.phase + (
                    math.pi * frequency_a / SAMPLE_RATE
                ) * steps
                sub = np.sin(phase_sub).astype(np.float32)
                mono += self.sub_level * sub

            envelope = voice.render_envelope(
                frames,
                SAMPLE_RATE,
                self.attack,
                self.decay,
                self.sustain,
                self.release
            )

            mono *= envelope * voice.velocity * 0.25

            # Small stereo spread, avoiding hard-panned notes.
            result[:, 0] += mono * 0.92
            result[:, 1] += mono

            voice.phase = (
                voice.phase
                + 2.0 * math.pi * frequency_a
                * frames / SAMPLE_RATE
            ) % (2.0 * math.pi)

            if voice.stage == "finished":
                finished.append(midi_note)

        for note in finished:
            self.voices.pop(note, None)

        return result

    # --------------------------------------------------------
    # CALLBACK
    # --------------------------------------------------------

    def callback(self, outdata, frames, time_info, status):
        outdata.fill(0)

        if status:
            # Status information is intentionally not printed here:
            # printing inside the audio callback can itself cause glitches.
            pass

        with self.lock:
            mixed = np.zeros((frames, 2), dtype=np.float32)

            # Synthesizer is independent of WAV playback.
            synth = self.render_synth(frames)
            samples = self.render_sample_voices(frames)
            mixed += synth * self.synth_volume
            mixed += samples * self.synth_volume

            # WAV playback with a short fade-in to prevent initial clicks.
            if self.wav_active and self.wav_audio is not None:
                audio = self.wav_audio
                available = len(audio) - int(self.wav_position)

                if available <= 0:
                    self.wav_active = False
                    self.wav_audio = None
                else:
                    count = min(frames, available)
                    positions = (
                        self.wav_position
                        + np.arange(count, dtype=np.float64)
                    )

                    idx0 = positions.astype(np.int64)
                    idx1 = np.minimum(idx0 + 1, len(audio) - 1)
                    fraction = (
                        positions - idx0
                    ).astype(np.float32)[:, None]

                    wav = (
                        audio[idx0] * (1.0 - fraction)
                        + audio[idx1] * fraction
                    )

                    fade_length = max(
                        1, int(SAMPLE_RATE * 0.010)
                    )
                    fade_positions = (
                        self.wav_fade_in_position
                        + np.arange(count, dtype=np.float32)
                    )
                    fade = np.minimum(
                        fade_positions / fade_length, 1.0
                    )
                    wav *= fade[:, None]

                    mixed[:count] += wav * self.wav_volume

                    self.wav_position += count
                    self.wav_fade_in_position += count

                    if self.wav_position >= len(audio):
                        self.wav_active = False
                        self.wav_audio = None

            # Low-pass filter on the combined synthesizer signal.
            # The state persists between blocks, avoiding block clicks.
            cutoff = float(
                np.clip(self.cutoff, 40.0, SAMPLE_RATE * 0.45)
            )
            alpha = 1.0 - math.exp(
                -2.0 * math.pi * cutoff / SAMPLE_RATE
            )

            filtered, self.filter_state = lfilter(
                [alpha],
                [1.0, -(1.0 - alpha)],
                mixed,
                axis=0,
                zi=self.filter_state
            )

            # Simple delay.
            if self.delay_mix > 0.001:
                delay_frames = int(
                    self.delay_seconds * SAMPLE_RATE
                )
                delay_frames = min(
                    delay_frames, len(self.delay_buffer) - 1
                )

                indices = (
                    self.delay_position
                    + np.arange(frames)
                ) % len(self.delay_buffer)

                read_indices = (
                    indices - delay_frames
                ) % len(self.delay_buffer)

                delayed = self.delay_buffer[read_indices].copy()

                self.delay_buffer[indices] = (
                    filtered + delayed * 0.25
                )

                filtered = (
                    filtered * (1.0 - self.delay_mix * 0.25)
                    + delayed * self.delay_mix
                )

                self.delay_position = (
                    self.delay_position + frames
                ) % len(self.delay_buffer)

            # Short feedback reverb.
            if self.reverb_mix > 0.001:
                indices = (
                    self.reverb_position
                    + np.arange(frames)
                ) % len(self.reverb_buffer)

                delayed = self.reverb_buffer[indices].copy()

                self.reverb_buffer[indices] = (
                    filtered + delayed * 0.35
                )

                filtered = (
                    filtered * (1.0 - self.reverb_mix * 0.25)
                    + delayed * self.reverb_mix * 0.6
                )

                self.reverb_position = (
                    self.reverb_position + frames
                ) % len(self.reverb_buffer)

            # Soft clipping limits peaks without abrupt hard clipping.
            outdata[:] = np.tanh(
                filtered * self.master_volume
            )

    def close(self):
        try:
            self.stop_wav()
            self.release_all()
            self.stream.stop()
            self.stream.close()
        except Exception as exc:
            print("[Audio] Shutdown:", exc)


# ============================================================
# GUI
# ============================================================

class SoundboardApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x800")
        self.root.minsize(760, 700)
        self.root.configure(bg="#111827")

        self.audio_cache = {}
        self.hotkey_queue = queue.Queue()
        self.listener = None

        self.pressed_keys = set()
        self.held_notes = {}
        self.recording = False
        self.record_start = 0.0
        self.recorded_events = []
        self.looping = False
        self.loop_after_ids = []
        self.loop_duration = 0.0
        self.sample_path = None

        self.octave = 4
        self.device = find_output_device()

        self.engine = None
        self.audio_error = None

        try:
            self.engine = AudioEngine(self.device)
        except Exception as exc:
            self.audio_error = str(exc)
            print("[Audio] Could not start output stream:", exc)

        self.load_tracks()
        self.build_gui()
        self.start_hotkeys()

        self.root.bind_all(
            "<KeyPress>", self.key_press, add="+"
        )
        self.root.bind_all(
            "<KeyRelease>", self.key_release, add="+"
        )
        self.root.bind(
            "<FocusOut>", self.release_all_keys, add="+"
        )
        self.root.bind_all(
            "<space>", self.space_stop, add="+"
        )

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        if self.audio_error:
            self.status.set(
                "Audio unavailable. Check output device and sample rate."
            )
        else:
            self.status.set(
                f"Ready | {SAMPLE_RATE} Hz | "
                f"{MAX_VOICES} synth voices"
            )

    def load_tracks(self):
        for key, (name, filename) in TRACKS.items():
            path = os.path.join(MUSIC_DIR, filename)

            if not os.path.isfile(path):
                print("[Audio] Missing:", path)
                continue

            try:
                self.audio_cache[key] = {
                    "name": name,
                    "audio": load_wav(path)
                }
                print("[Audio] Loaded:", path)
            except Exception as exc:
                print("[Audio] Failed to load", path, exc)

    def build_gui(self):
        # Optional background image.
        self.background_photo = None

        if os.path.isfile(BACKGROUND_FILE):
            try:
                image = Image.open(BACKGROUND_FILE).convert("RGB")
                image = image.resize(
                    (900, 800), Image.Resampling.LANCZOS
                )
                self.background_photo = ImageTk.PhotoImage(image)
                background = tk.Label(
                    self.root, image=self.background_photo, bd=0
                )
                background.place(x=0, y=0, relwidth=1, relheight=1)
            except Exception as exc:
                print("[GUI] Background image:", exc)

        container = tk.Frame(
            self.root, bg="#111827", bd=0
        )
        container.pack(fill="both", expand=True, padx=14, pady=10)

        tk.Label(
            container,
            text="JESUS 2026 SOUNDBOARD",
            font=("Segoe UI", 20, "bold"),
            fg="#F9FAFB",
            bg="#111827"
        ).pack(pady=(0, 2))

        tk.Label(
            container,
            text="WAV SOUNDBOARD  +  POLY-8 SYNTHESIZER",
            font=("Segoe UI", 10),
            fg="#93C5FD",
            bg="#111827"
        ).pack(pady=(0, 10))

        # ----------------------------------------------------
        # WAV SOUNDBOARD
        # ----------------------------------------------------

        wav_frame = tk.LabelFrame(
            container,
            text="WAV SOUNDBOARD",
            fg="white",
            bg="#111827",
            font=("Segoe UI", 10, "bold"),
            padx=8,
            pady=6
        )
        wav_frame.pack(fill="x", pady=(0, 10))

        for col in range(5):
            wav_frame.grid_columnconfigure(col, weight=1)

        self.wav_buttons = {}

        for index, (key, (name, filename)) in enumerate(TRACKS.items()):
            loaded = key in self.audio_cache

            button = tk.Button(
                wav_frame,
                text=f"{key}  {name}\nALT+{key}",
                command=lambda k=key: self.play_track(k),
                font=("Segoe UI", 9, "bold"),
                bg="#2563EB" if loaded else "#374151",
                fg="white",
                activebackground="#3B82F6",
                activeforeground="white",
                disabledforeground="#9CA3AF",
                relief="flat",
                padx=5,
                pady=7,
                state=(
                    "normal" if loaded and self.engine else "disabled"
                )
            )

            button.grid(
                row=index // 5,
                column=index % 5,
                padx=3,
                pady=3,
                sticky="ew"
            )
            self.wav_buttons[key] = button

        wav_controls = tk.Frame(wav_frame, bg="#111827")
        wav_controls.grid(
            row=2, column=0, columnspan=5,
            sticky="ew", pady=(5, 0)
        )

        tk.Button(
            wav_controls,
            text="STOP WAV",
            command=self.stop_wav,
            bg="#991B1B",
            fg="white",
            activebackground="#B91C1C",
            relief="flat",
            padx=12,
            pady=4
        ).pack(side="left")

        self.wav_volume = tk.DoubleVar(value=WAV_VOLUME)

        tk.Label(
            wav_controls,
            text="WAV volume",
            bg="#111827",
            fg="white"
        ).pack(side="left", padx=(14, 5))

        tk.Scale(
            wav_controls,
            from_=0.0,
            to=1.0,
            resolution=0.01,
            orient="horizontal",
            variable=self.wav_volume,
            command=self.change_wav_volume,
            showvalue=True,
            length=160,
            bg="#111827",
            fg="white",
            troughcolor="#374151",
            highlightthickness=0
        ).pack(side="left")

        # ----------------------------------------------------
        # SYNTHESIZER
        # ----------------------------------------------------

        synth_frame = tk.LabelFrame(
            container,
            text="POLY-8 SYNTHESIZER",
            fg="white",
            bg="#111827",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8
        )
        synth_frame.pack(fill="both", expand=True, pady=(0, 8))

        # Top controls
        top = tk.Frame(synth_frame, bg="#111827")
        top.pack(fill="x", pady=(0, 8))

        tk.Label(
            top,
            text="Waveform",
            bg="#111827",
            fg="white"
        ).pack(side="left")

        self.waveform_var = tk.StringVar(value="Saw")

        waveform_menu = ttk.Combobox(
            top,
            textvariable=self.waveform_var,
            values=["Sine", "Saw", "Square", "Triangle"],
            state="readonly",
            width=11
        )
        waveform_menu.pack(side="left", padx=6)
        waveform_menu.bind(
            "<<ComboboxSelected>>", self.change_waveform
        )

        tk.Label(
            top,
            text="Octave",
            bg="#111827",
            fg="white"
        ).pack(side="left", padx=(15, 4))

        tk.Button(
            top, text="−", width=3,
            command=lambda: self.change_octave(-1)
        ).pack(side="left")

        self.octave_label = tk.Label(
            top,
            text=str(self.octave),
            bg="#111827",
            fg="#93C5FD",
            width=3,
            font=("Segoe UI", 11, "bold")
        )
        self.octave_label.pack(side="left")

        tk.Button(
            top, text="+", width=3,
            command=lambda: self.change_octave(1)
        ).pack(side="left")

        tk.Button(
            top,
            text="RELEASE ALL",
            command=self.release_all_keys,
            bg="#374151",
            fg="white",
            relief="flat"
        ).pack(side="right")

        # WAV sampler and performance recorder
        sampler = tk.Frame(synth_frame, bg="#111827")
        sampler.pack(fill="x", pady=(0, 8))

        self.sample_label = tk.Label(
            sampler, text="Sampler: no WAV loaded",
            bg="#111827", fg="#FBBF24", anchor="w"
        )
        self.sample_label.pack(side="left", fill="x", expand=True)

        tk.Button(
            sampler, text="LOAD / DROP WAV",
            command=self.choose_sample, bg="#7C3AED", fg="white",
            relief="flat", padx=8, pady=4
        ).pack(side="left", padx=3)

        tk.Button(
            sampler, text="SYNTH MODE",
            command=self.switch_to_synth, bg="#374151", fg="white",
            relief="flat", padx=8, pady=4
        ).pack(side="left", padx=3)

        self.record_button = tk.Button(
            sampler, text="● REC", command=self.toggle_recording,
            bg="#B91C1C", fg="white", relief="flat", padx=8, pady=4
        )
        self.record_button.pack(side="left", padx=3)

        tk.Button(
            sampler, text="PLAY LOOP", command=self.play_loop,
            bg="#047857", fg="white", relief="flat", padx=8, pady=4
        ).pack(side="left", padx=3)

        tk.Button(
            sampler, text="STOP LOOP", command=self.stop_loop,
            bg="#92400E", fg="white", relief="flat", padx=8, pady=4
        ).pack(side="left", padx=3)

        self.drop_target = tk.Label(
            synth_frame,
            text=("Drag a WAV file here to map it across every key" if DND_AVAILABLE
                  else "Drag-and-drop requires tkinterdnd2; LOAD / DROP WAV still works"),
            bg="#1F2937", fg="#D1D5DB", relief="groove", pady=5
        )
        self.drop_target.pack(fill="x", pady=(0, 8))
        if DND_AVAILABLE:
            try:
                self.drop_target.drop_target_register(DND_FILES)
                self.drop_target.dnd_bind("<<Drop>>", self.drop_sample)
            except Exception as exc:
                print("[GUI] Drag-and-drop setup failed:", exc)

        # Keyboard display
        keyboard_frame = tk.Frame(synth_frame, bg="#111827")
        keyboard_frame.pack(fill="x", pady=(2, 12))

        tk.Label(
            keyboard_frame,
            text="Play with your computer keyboard or click the keys",
            bg="#111827",
            fg="#D1D5DB",
            font=("Segoe UI", 9)
        ).pack(pady=(0, 6))

        piano_row = tk.Frame(keyboard_frame, bg="#111827")
        piano_row.pack(fill="x")

        self.piano_buttons = {}

        black_notes = {1, 3, 6, 8, 10, 13}
        key_names = list(KEY_SEMITONES.keys())

        for key_name, semitone in KEY_SEMITONES.items():
            black = semitone in black_notes

            button = tk.Button(
                piano_row,
                text=key_name.upper(),
                font=("Segoe UI", 9, "bold"),
                bg="#111827" if black else "#F3F4F6",
                fg="white" if black else "#111827",
                activebackground="#60A5FA",
                relief="raised",
                bd=1,
                padx=0,
                pady=16,
                takefocus=False
            )
            button.pack(
                side="left", fill="x", expand=True, padx=1
            )

            button.bind(
                "<ButtonPress-1>",
                lambda event, k=key_name: self.note_press(k)
            )
            button.bind(
                "<ButtonRelease-1>",
                lambda event, k=key_name: self.note_release(k)
            )

            self.piano_buttons[key_name] = button

        tk.Label(
            keyboard_frame,
            text="A W S E D F T G Y H U J K O L     |     [ / ] octave",
            bg="#111827",
            fg="#9CA3AF",
            font=("Consolas", 9)
        ).pack(pady=(5, 0))

        # Synth controls
        controls = tk.Frame(synth_frame, bg="#111827")
        controls.pack(fill="x")

        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)

        self.adsr_vars = {
            "attack": tk.DoubleVar(value=0.010),
            "decay": tk.DoubleVar(value=0.12),
            "sustain": tk.DoubleVar(value=0.70),
            "release": tk.DoubleVar(value=0.080),
        }

        self.add_slider(
            controls, "Attack", "attack",
            0.001, 1.0, 0, 0,
            self.change_adsr
        )
        self.add_slider(
            controls, "Decay", "decay",
            0.001, 1.0, 0, 1,
            self.change_adsr
        )
        self.add_slider(
            controls, "Sustain", "sustain",
            0.0, 1.0, 1, 0,
            self.change_adsr
        )
        self.add_slider(
            controls, "Release", "release",
            0.005, 2.0, 1, 1,
            self.change_adsr
        )

        self.cutoff_var = tk.DoubleVar(value=12000)
        self.add_slider(
            controls, "Filter cutoff", "cutoff",
            200, 18000, 2, 0,
            self.change_filter
        )

        self.detune_var = tk.DoubleVar(value=5.0)
        self.add_slider(
            controls, "Detune (cents)", "detune",
            0, 30, 2, 1,
            self.change_detune
        )

        self.sub_var = tk.DoubleVar(value=0.0)
        self.add_slider(
            controls, "Sub oscillator", "sub",
            0, 0.8, 3, 0,
            self.change_sub
        )

        self.synth_volume = tk.DoubleVar(value=SYNTH_VOLUME)
        self.add_slider(
            controls, "Synth volume", "synth_volume",
            0, 0.8, 3, 1,
            self.change_synth_volume
        )

        # Effects
        effects = tk.Frame(synth_frame, bg="#111827")
        effects.pack(fill="x", pady=(8, 0))

        self.delay_var = tk.DoubleVar(value=0.0)
        self.reverb_var = tk.DoubleVar(value=0.0)

        tk.Label(
            effects,
            text="Delay",
            fg="white",
            bg="#111827"
        ).pack(side="left")

        tk.Scale(
            effects,
            from_=0.0, to=0.7,
            resolution=0.01,
            orient="horizontal",
            variable=self.delay_var,
            command=self.change_delay,
            showvalue=True,
            length=150,
            bg="#111827",
            fg="white",
            troughcolor="#374151",
            highlightthickness=0
        ).pack(side="left", padx=(2, 12))

        tk.Label(
            effects,
            text="Reverb",
            fg="white",
            bg="#111827"
        ).pack(side="left")

        tk.Scale(
            effects,
            from_=0.0, to=0.7,
            resolution=0.01,
            orient="horizontal",
            variable=self.reverb_var,
            command=self.change_reverb,
            showvalue=True,
            length=150,
            bg="#111827",
            fg="white",
            troughcolor="#374151",
            highlightthickness=0
        ).pack(side="left", padx=2)

        # Master
        master = tk.Frame(container, bg="#111827")
        master.pack(fill="x", pady=(0, 4))

        self.master_var = tk.DoubleVar(value=MASTER_VOLUME)

        tk.Label(
            master,
            text="MASTER",
            fg="white",
            bg="#111827",
            font=("Segoe UI", 9, "bold")
        ).pack(side="left")

        tk.Scale(
            master,
            from_=0.0, to=1.0,
            resolution=0.01,
            orient="horizontal",
            variable=self.master_var,
            command=self.change_master,
            showvalue=True,
            length=200,
            bg="#111827",
            fg="white",
            troughcolor="#374151",
            highlightthickness=0
        ).pack(side="left", padx=8)

        self.status = tk.StringVar(value="Starting...")
        tk.Label(
            container,
            textvariable=self.status,
            fg="#D1D5DB",
            bg="#111827",
            anchor="w",
            wraplength=850
        ).pack(fill="x", pady=(3, 0))

    # --------------------------------------------------------
    # SLIDER HELPER
    # --------------------------------------------------------

    def add_slider(self, parent, label, key, minimum, maximum,
                   row, column, callback):
        box = tk.Frame(parent, bg="#111827")
        box.grid(
            row=row, column=column,
            padx=6, pady=3, sticky="ew"
        )

        tk.Label(
            box,
            text=label,
            bg="#111827",
            fg="#E5E7EB",
            anchor="w"
        ).pack(fill="x")

        if key in self.adsr_vars:
            variable = self.adsr_vars[key]
        elif key == "cutoff":
            variable = self.cutoff_var
        elif key == "detune":
            variable = self.detune_var
        elif key == "sub":
            variable = self.sub_var
        else:
            variable = self.synth_volume

        tk.Scale(
            box,
            from_=minimum,
            to=maximum,
            resolution=0.001 if maximum <= 2 else 1,
            orient="horizontal",
            variable=variable,
            command=lambda value, k=key: callback(k, value),
            showvalue=True,
            bg="#111827",
            fg="white",
            troughcolor="#374151",
            highlightthickness=0
        ).pack(fill="x")

    # --------------------------------------------------------
    # WAV CONTROLS
    # --------------------------------------------------------

    def play_track(self, key):
        if not self.engine:
            return

        track = self.audio_cache.get(key)
        if not track:
            self.status.set(f"Missing WAV file for sound {key}.")
            return

        self.engine.play_wav(track["audio"])
        self.status.set(f"WAV playing: {track['name']}")

    def stop_wav(self):
        if self.engine:
            self.engine.stop_wav()
        self.status.set("WAV stopped. Synthesizer remains available.")

    def change_wav_volume(self, value):
        if self.engine:
            self.engine.wav_volume = float(value)

    # --------------------------------------------------------
    # SYNTH CONTROLS
    # --------------------------------------------------------

    def change_waveform(self, _event=None):
        if self.engine:
            self.engine.set_waveform(self.waveform_var.get())
        self.status.set(f"Waveform: {self.waveform_var.get()}")

    def change_octave(self, amount):
        self.octave = max(1, min(7, self.octave + amount))
        self.octave_label.configure(text=str(self.octave))
        self.status.set(f"Synth octave: {self.octave}")

    def midi_note(self, key):
        # MIDI note 60 = C4.
        return 12 * (self.octave + 1) + KEY_SEMITONES[key]

    def note_press(self, key):
        if not self.engine or key not in KEY_SEMITONES:
            return

        if key in self.pressed_keys:
            return

        self.pressed_keys.add(key)
        note = self.midi_note(key)
        self.held_notes[key] = note
        self.engine.note_on(note)
        self.record_note_event("on", note)

        button = self.piano_buttons.get(key)
        if button:
            button.configure(relief="sunken")

    def note_release(self, key):
        self.pressed_keys.discard(key)
        note = self.held_notes.pop(key, None)

        if self.engine and note is not None:
            self.engine.note_off(note)
            self.record_note_event("off", note)

        button = self.piano_buttons.get(key)
        if button:
            button.configure(relief="raised")

    def key_press(self, event):
        key = event.keysym.lower()

        if key == "bracketleft":
            self.change_octave(-1)
            return

        if key == "bracketright":
            self.change_octave(1)
            return

        if key in KEY_SEMITONES:
            self.note_press(key)

    def key_release(self, event):
        key = event.keysym.lower()

        if key in KEY_SEMITONES:
            self.note_release(key)

    def release_all_keys(self, _event=None):
        for key in list(self.held_notes):
            self.note_release(key)

        if self.engine:
            self.engine.release_all()

    def space_stop(self, _event=None):
        self.stop_wav()
        return "break"

    def change_adsr(self, key, value):
        if not self.engine:
            return

        self.engine.set_envelope(**{key: float(value)})

    def change_filter(self, _key, value):
        if self.engine:
            self.engine.set_filter(cutoff=float(value))

    def change_detune(self, _key, value):
        if self.engine:
            self.engine.set_detune(float(value))

    def change_sub(self, _key, value):
        if self.engine:
            self.engine.set_sub_level(float(value))

    def change_synth_volume(self, _key, value):
        if self.engine:
            self.engine.synth_volume = float(value)

    def change_delay(self, value):
        if self.engine:
            self.engine.set_effects(delay=float(value))

    def change_reverb(self, value):
        if self.engine:
            self.engine.set_effects(reverb=float(value))

    def change_master(self, value):
        if self.engine:
            self.engine.master_volume = float(value)

    # --------------------------------------------------------
    # GLOBAL HOTKEYS
    # --------------------------------------------------------

    def start_hotkeys(self):
        hotkeys = {}

        for key in TRACKS:
            hotkeys[f"<alt>+{key}"] = (
                lambda k=key: self.hotkey_queue.put(k)
            )

        try:
            self.listener = keyboard.GlobalHotKeys(hotkeys)
            self.listener.start()
        except Exception as exc:
            print("[Keyboard] Global hotkeys unavailable:", exc)

    def process_hotkeys(self):
        try:
            while True:
                key = self.hotkey_queue.get_nowait()
                self.play_track(key)
        except queue.Empty:
            pass

        if self.root.winfo_exists():
            self.root.after(40, self.process_hotkeys)

    # --------------------------------------------------------
    # SHUTDOWN
    # --------------------------------------------------------

    def close(self):
        self.stop_loop()
        self.recording = False
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass

        if self.engine:
            self.engine.close()

        self.root.destroy()


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    app = SoundboardApp(root)
    root.after(40, app.process_hotkeys)
    root.mainloop()


if __name__ == "__main__":
    main()
