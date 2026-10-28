# JESUS alarm (with Background Picture Support)

GUI Soundboard that plays 6 WAV files through your **Realtek High Definition Audio** output at 50% volume.

## Folder Structure:
- `soundboard.py`
- `run.bat`
- `music/` -> Place `track1.wav` to `track6.wav` here.
- `pics/`  -> Place your **Black Wildebeest (GNU)** picture here (e.g. `gnu.jpg`, `gnu.png`).

## Features:
- **Title Bar:** Window titled "JESUS alarm"
- **Background Picture:** Automatically renders any picture inside the `pics/` folder as the window background.
- **6 Clickable Buttons:** One button for each WAV track overlaying the image.
- **Global Hotkeys:** Background trigger using `ALT + 1` through `ALT + 6`.
- **Audio Output:** Fixed 50% volume forced to Realtek Laptop Speakers.
