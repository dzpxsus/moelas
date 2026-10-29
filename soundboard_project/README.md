# JESUS 2026 Soundboard - Sampler Edition

## Included
- `soundboard.py` - updated soundboard with WAV sampler, synth keyboard, note-event recording and loop playback.
- `soundboard_original_backup.py` - copy of the earlier soundboard script for reference/rollback.
- `requirements.txt` - Python dependencies.
- `run.bat` - launches the app from this folder.
- `music/` and `pics/` - folders for your own audio and optional image assets.

## Requirements
- Windows with Python 3.10+ (Python 3.12 is suitable).
- Working audio output device.

Install dependencies from PowerShell in this folder:

```powershell
python -m pip install --user -r requirements.txt
```

If your network returns HTTP 403 for `tkinterdnd2`, skip it. Drag-and-drop will be unavailable, but use the **LOAD WAV** button instead.

## Run

Double-click `run.bat`, or run from PowerShell:

```powershell
cd "C:\path\to\soundboard_project"
python soundboard.py
```

## Your existing media

The ZIP does not contain your personal WAV files or background images. Copy your existing `music` and `pics` contents into these folders after extracting, or extract the project into a new folder and copy those folders from your current project.

The default soundboard expects these WAV files in `music/`:
- `tarzan.wav`
- `bipbip.wav`
- `badumtss.wav`
- `r2D2.wav`
- `scout.wav`
- `batman.wav`
- `sound7.wav` (optional)
- `sound8.wav` (optional)
- `sound9.wav` (optional)
- `sound10.wav` (optional)

Missing optional sound files are reported in the console but do not by themselves prevent the app from opening.

## Sampler and recording notes
- Load a WAV file with **LOAD WAV**; if drag-and-drop support is installed, you can also drop a file onto the sampler target.
- Sampler mode plays the loaded WAV at different pitches from the keyboard.
- REC / STOP REC records performance note events in memory; PLAY LOOP / STOP LOOP loops those events. It does not export a rendered WAV recording.

## Troubleshooting
- If the audio output fails, check the selected Windows output device and confirm another app can play audio.
- Run `python -m py_compile soundboard.py` to check Python syntax.
- Keep your original project folder until you've confirmed the new copy works.
