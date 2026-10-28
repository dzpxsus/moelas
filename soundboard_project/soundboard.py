
import queue
import threading
import os
import tkinter as tk

import sounddevice as sd
import soundfile as sf
from pynput import keyboard
from PIL import Image, ImageTk
from scipy.signal import resample_poly
from math import gcd


# ============================================================
# CONFIGURATION
# ============================================================

MUSIC_DIR = "music"
PICS_DIR = "pics"

TRACK_FILES = {
    "1": ("tarzan", os.path.join(MUSIC_DIR, "tarzan.wav")),
    "2": ("bipbip", os.path.join(MUSIC_DIR, "bipbip.wav")),
    "3": ("badumtss", os.path.join(MUSIC_DIR, "badumtss.wav")),
    "4": ("R2D2", os.path.join(MUSIC_DIR, "r2D2.wav")),
    "5": ("scout", os.path.join(MUSIC_DIR, "scout.wav")),
    "6": ("batman", os.path.join(MUSIC_DIR, "batman.wav")),
    "7": ("sound7", os.path.join(MUSIC_DIR, "sound7.wav")),
    "8": ("sound8", os.path.join(MUSIC_DIR, "sound8.wav")),
    "9": ("sound9", os.path.join(MUSIC_DIR, "sound9.wav")),
    "0": ("gay", os.path.join(MUSIC_DIR, "gay.wav")),
}

TARGET_DEVICE_INDEX = 17
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2

# 0.05 = 5% signal amplitude
PLAYBACK_VOLUME = 0.05

WINDOW_WIDTH = 450
WINDOW_HEIGHT = 650

BACKGROUND_COLOR = "#1E1E2E"
OVERLAY_COLOR = "#000000"

BUTTON_COLORS = [
    "#89B4FA",
    "#A6E3A1",
    "#F9E2AF",
    "#FAB387",
    "#CBA6F7",
    "#F5C2E7",
    "#94E2D5",
    "#F38BA8",
    "#B4BEFE",
    "#A6E3A1",
]


class JesusAlarmSoundboard:

    def __init__(self, root):
        self.root = root
        self.root.title("JASUS 2026")
        self.root.geometry(
            f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}"
        )
        self.root.resizable(False, False)

        self.audio_cache = {}
        self.command_queue = queue.Queue()
        self.running = True
        self.target_device = TARGET_DEVICE_INDEX
        self.hotkey_listener = None
        self.current_stream = None

        self._find_realtek_device()
        self._preload_audio()
        self._build_gui()
        self._start_threads()

    # ========================================================
    # AUDIO DEVICE
    # ========================================================

    def _find_realtek_device(self):
        try:
            devices = sd.query_devices()

            # Prefer the configured device if it is valid
            if 0 <= self.target_device < len(devices):
                dev = devices[self.target_device]

                if dev["max_output_channels"] >= TARGET_CHANNELS:
                    print(
                        f"[Hardware] Output device "
                        f"{self.target_device}: {dev['name']}"
                    )
                    print(
                        f"[Hardware] Default sample rate: "
                        f"{dev['default_samplerate']} Hz"
                    )
                    return

            # Otherwise find a Realtek output device
            for i, dev in enumerate(devices):
                if (
                    dev["max_output_channels"] >= TARGET_CHANNELS
                    and "Realtek" in dev["name"]
                ):
                    self.target_device = i
                    print(
                        f"[Hardware] Realtek output: "
                        f"{i} - {dev['name']}"
                    )
                    return

            # Final fallback: system default output
            default_output = sd.default.device[1]

            if default_output is not None and default_output >= 0:
                self.target_device = int(default_output)
                print(
                    f"[Hardware] Using default output: "
                    f"{self.target_device}"
                )
            else:
                print("[Hardware Error] No output device found.")

        except Exception as e:
            print(f"[Hardware Error] {e}")

    # ========================================================
    # PRELOAD AND RESAMPLE AUDIO
    # ========================================================

    def _preload_audio(self):
        os.makedirs(MUSIC_DIR, exist_ok=True)

        for key, (name, filepath) in TRACK_FILES.items():

            if not os.path.exists(filepath):
                print(f"[Missing Audio] {filepath}")
                continue

            try:
                # Always load audio as a 2D array
                # Shape: frames x channels
                data, original_rate = sf.read(
                    filepath,
                    dtype="float32",
                    always_2d=True,
                )

                original_channels = data.shape[1]

                # Convert to stereo if necessary
                if original_channels == 1:
                    data = data.repeat(2, axis=1)

                elif original_channels > 2:
                    data = data[:, :2]

                # Resample to 48,000 Hz when necessary
                if original_rate != TARGET_SAMPLE_RATE:

                    divisor = gcd(
                        int(original_rate),
                        TARGET_SAMPLE_RATE,
                    )

                    up = TARGET_SAMPLE_RATE // divisor
                    down = int(original_rate) // divisor

                    data = resample_poly(
                        data,
                        up,
                        down,
                        axis=0,
                    ).astype("float32")

                    print(
                        f"[Audio] Resampled {name}: "
                        f"{original_rate} -> "
                        f"{TARGET_SAMPLE_RATE} Hz"
                    )

                # Apply volume
                data *= PLAYBACK_VOLUME

                # Cache audio in memory
                self.audio_cache[key] = {
                    "data": data,
                    "samplerate": TARGET_SAMPLE_RATE,
                }

                print(
                    f"[Audio] Loaded: {filepath} "
                    f"({TARGET_SAMPLE_RATE} Hz, stereo)"
                )

            except Exception as e:
                print(
                    f"[Audio Error] Could not load "
                    f"{filepath}: {e}"
                )

    # ========================================================
    # BACKGROUND IMAGE
    # ========================================================

    def _find_bg_image(self):
        os.makedirs(PICS_DIR, exist_ok=True)

        valid_extensions = (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".webp",
        )

        for filename in os.listdir(PICS_DIR):
            if filename.lower().endswith(valid_extensions):
                return os.path.join(PICS_DIR, filename)

        return None

    # ========================================================
    # GUI
    # ========================================================

    def _build_gui(self):

        bg_image_path = self._find_bg_image()

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=BACKGROUND_COLOR,
        )
        self.canvas.pack(fill="both", expand=True)

        # Background image
        if bg_image_path:
            try:
                with Image.open(bg_image_path) as image:
                    pil_img = image.convert("RGB").resize(
                        (WINDOW_WIDTH, WINDOW_HEIGHT),
                        Image.Resampling.LANCZOS,
                    )

                self.bg_photo = ImageTk.PhotoImage(pil_img)

                self.canvas.create_image(
                    0,
                    0,
                    image=self.bg_photo,
                    anchor="nw",
                )

                print(f"[GUI] Background: {bg_image_path}")

            except Exception as e:
                print(f"[GUI Image Error] {e}")

        else:
            print(
                "[GUI] No background image found. "
                "Using dark background."
            )

        # Dark overlay
        # Tkinter Frame backgrounds are not alpha-transparent.
        overlay_frame = tk.Frame(
            self.canvas,
            bg=OVERLAY_COLOR,
            bd=0,
        )

        overlay_frame.place(
            relx=0.5,
            rely=0.5,
            anchor="center",
            relwidth=0.90,
            relheight=0.95,
        )

        # Header
        header = tk.Label(
            overlay_frame,
            text="GNU Alert",
            font=("Helvetica", 16, "bold"),
            fg="#F38BA8",
            bg=OVERLAY_COLOR,
            pady=8,
        )
        header.pack()

        # Status
        self.status_label = tk.Label(
            overlay_frame,
            text=(
                "Jesus - A identificar Gnus desde 2007\n"
                "Atalhos: ALT + 1-9, 0"
            ),
            font=("Helvetica", 9),
            fg="#A6ADC8",
            bg=OVERLAY_COLOR,
            justify="center",
        )
        self.status_label.pack(pady=(0, 8))

        # Buttons container
        frame = tk.Frame(
            overlay_frame,
            bg=OVERLAY_COLOR,
        )
        frame.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=5,
        )

        # 10 buttons: 2 columns x 5 rows
        for idx, (key, (title, filepath)) in enumerate(
            TRACK_FILES.items()
        ):
            row = idx // 2
            col = idx % 2

            available = key in self.audio_cache

            btn = tk.Button(
                frame,
                text=f"{title}\n(ALT + {key})",
                font=("Helvetica", 10, "bold"),
                bg=BUTTON_COLORS[idx],
                fg="#11111B",
                activebackground="#CDD6F4",
                relief="flat",
                cursor="hand2",
                state="normal" if available else "disabled",
                command=lambda k=key: self.trigger_sound(k),
            )

            btn.grid(
                row=row,
                column=col,
                padx=6,
                pady=5,
                sticky="nsew",
            )

            frame.grid_columnconfigure(
                col,
                weight=1,
                uniform="buttons",
            )

            frame.grid_rowconfigure(
                row,
                weight=1,
                uniform="buttons",
            )

        # Footer
        footer = tk.Label(
            overlay_frame,
            text="10 SOUND EFFECTS | JASUS 2026",
            font=("Helvetica", 8, "bold"),
            fg="#A6ADC8",
            bg=OVERLAY_COLOR,
            pady=5,
        )
        footer.pack()

    # ========================================================
    # PLAY SOUND
    # ========================================================

    def trigger_sound(self, track_key):
        if track_key in self.audio_cache:
            self.command_queue.put(track_key)
        else:
            print(
                f"[Audio] Sound {track_key} unavailable."
            )

    def audio_worker(self):

        while self.running:
            try:
                track_key = self.command_queue.get(
                    timeout=0.1
                )

            except queue.Empty:
                continue

            try:
                if not self.running:
                    continue

                track = self.audio_cache.get(track_key)

                if track is not None:
                    # Stop the previous sound before playing
                    # the new one, avoiding overlapping effects.
                    sd.stop()

                    self.current_stream = sd.play(
                        track["data"],
                        samplerate=track["samplerate"],
                        device=self.target_device,
                        blocking=False,
                    )

                    print(f"[Audio] Playing: {track_key}")

            except Exception as e:
                print(
                    f"[Playback Error] "
                    f"Sound {track_key}: {e}"
                )

            finally:
                self.command_queue.task_done()

    # ========================================================
    # GLOBAL KEYBOARD SHORTCUTS
    # ========================================================

    def _start_threads(self):

        threading.Thread(
            target=self.audio_worker,
            daemon=True,
        ).start()

        hotkeys = {
            f"<alt>+{i}": (
                lambda k=str(i): self.trigger_sound(k)
            )
            for i in range(1, 10)
        }

        # ALT + 0 triggers sound option 10
        hotkeys["<alt>+0"] = (
            lambda: self.trigger_sound("0")
        )

        self.hotkey_listener = keyboard.GlobalHotKeys(
            hotkeys
        )
        self.hotkey_listener.start()

        print(
            "[Keyboard] Shortcuts enabled: "
            "ALT + 1-9 and ALT + 0"
        )

    # ========================================================
    # CLOSE APPLICATION
    # ========================================================

    def on_close(self):

        self.running = False

        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()

        try:
            sd.stop()
        except Exception:
            pass

        self.root.destroy()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    root = tk.Tk()
    app = JesusAlarmSoundboard(root)

    root.protocol(
        "WM_DELETE_WINDOW",
        app.on_close,
    )

    root.mainloop()