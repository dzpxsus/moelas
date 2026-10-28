# 🎵 JASUS 2026 Soundboard

**A lightweight Python soundboard with global keyboard shortcuts, custom sound effects, and a personalised graphical interface.**

JASUS (Jesus Alarm Soundboard) is a Windows desktop application built with Python and Tkinter. It lets you trigger memorable audio clips instantly using keyboard shortcuts, even when another application is in focus.

Designed for quick reactions, office humour, memorable movie moments, and everyday fun. 😎

## ✨ Features

- 🔊 **10 sound effects** accessible through dedicated buttons.
- ⌨️ **Global keyboard shortcuts:** `ALT + 1` to `ALT + 9`, plus `ALT + 0` for sound 10.
- ⚡ **Preloaded audio:** sound files are loaded into memory at startup for responsive playback.
- 🎚️ **Volume control:** configurable playback amplitude.
- 🎧 **Realtek audio support:** configurable output device, targeting 48,000 Hz stereo playback.
- 🔄 **Automatic resampling:** WAV files with different sample rates are converted in memory to 48 kHz.
- 🖼️ **Custom background:** automatically loads an image from the `pics` folder.
- 🎨 **Graphical interface:** colour-coded buttons arranged in a 2-column layout.
- 🧵 **Background audio worker:** handles playback requests separately from the GUI.
- 📁 **Customisable sounds:** replace the WAV files and labels to create your own soundboard.

## 🖥️ Screenshot

Add a screenshot of the application to your repository and save it as `docs/screenshot.png`.

Then uncomment or add the following Markdown:

```markdown
![JASUS 2026 Soundboard](docs/screenshot.png)
```

## 🛠️ Technologies

- Python 3
- Tkinter
- SoundDevice
- SoundFile
- NumPy
- SciPy
- Pillow
- pynput

## 📋 Requirements

- Windows 10 or Windows 11
- Python 3.10 or later recommended
- An audio output device
- WAV audio files
- Administrator rights are not normally required for the Python package installation, provided Python and pip are available and permitted on your system

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/JASUS-2026-Soundboard.git
cd JASUS-2026-Soundboard
```

Replace `YOUR_USERNAME` with your GitHub username.

Alternatively, download the repository as a ZIP file and extract it.

### 2. Install dependencies

Open PowerShell in the project folder and run:

```powershell
python -m pip install sounddevice soundfile pynput numpy Pillow scipy
```

If `python` is not recognised, try:

```powershell
py -m pip install sounddevice soundfile pynput numpy Pillow scipy
```

### 3. Configure the sound files

Create the following folders beside the Python script:

```text
JASUS-2026-Soundboard/
├── soundboard.py
├── README.md
├── music/
│   ├── tarzan.wav
│   ├── bipbip.wav
│   ├── badumtss.wav
│   ├── r2D2.wav
│   ├── scout.wav
│   ├── batman.wav
│   ├── sound7.wav
│   ├── sound8.wav
│   ├── sound9.wav
│   └── sound10.wav
└── pics/
    └── background.jpg
```

The background image is optional. Supported formats include PNG, JPG, JPEG, BMP, and WEBP.

Replace the example audio files with your own WAV files. Update the `TRACK_FILES` dictionary in the script if your filenames or sound labels are different.

### 4. Run the application

```powershell
python soundboard.py
```

## ⌨️ Keyboard Shortcuts

| Shortcut | Sound |
|---|---|
| `ALT + 1` | Tarzan |
| `ALT + 2` | Bipbip |
| `ALT + 3` | Badumtss |
| `ALT + 4` | R2D2 |
| `ALT + 5` | Scout |
| `ALT + 6` | Batman |
| `ALT + 7` | Custom sound 7 |
| `ALT + 8` | Custom sound 8 |
| `ALT + 9` | Custom sound 9 |
| `ALT + 0` | Custom sound 10 |

The shortcuts are registered globally, allowing sounds to be triggered while working in other applications.

**Note:** Some applications or system-level shortcuts may intercept certain key combinations. Global keyboard monitoring may also be restricted by organisational security policies.

## ⚙️ Configuration

The main settings are defined near the top of `soundboard.py`.

### Playback volume

```python
PLAYBACK_VOLUME = 0.05
```

This applies 5% signal amplitude to the loaded audio. It is not a guarantee of 5% perceived loudness.

### Sample rate

```python
TARGET_SAMPLE_RATE = 48000
TARGET_CHANNELS = 2
```

Audio is converted to 48,000 Hz and stereo during loading. This is intended for the tested Realtek output configuration.

### Output device

```python
TARGET_DEVICE_INDEX = 17
```

The device index depends on the audio devices available on your computer. If the index changes, update the configuration or adapt the device-selection logic to find the desired output automatically.

### Custom sounds

Edit the `TRACK_FILES` dictionary to change each sound's display name and WAV file path.

For example:

```python
"7": ("laugh", os.path.join(MUSIC_DIR, "laugh.wav")),
```

The corresponding file must exist in the `music` folder.

## 🔧 Troubleshooting

### No sound is played

- Check that the WAV file exists in the `music` folder.
- Check the console for missing-file or playback errors.
- Confirm that the configured audio device is available.
- Check the Windows volume mixer and selected output device.

### Invalid sample rate

The application resamples audio to 48 kHz before playback. If playback still fails, verify that the selected output device supports 48 kHz stereo and that Windows audio settings permit playback.

### A keyboard shortcut does not work

- Ensure the application is running.
- Check whether another application intercepts the shortcut.
- Check whether organisational security policies restrict global keyboard monitoring.

### A button is disabled

The associated WAV file was not successfully loaded. Check the console for the relevant error.

## 🔒 Privacy

JASUS is designed as a local desktop application. It loads local audio and image files and does not require an online account or cloud service to play sounds.

The global keyboard listener monitors registered shortcut combinations while the application is running. Use it in accordance with your organisation's security policies.

## 🗺️ Roadmap

Potential future improvements:

- [ ] Adjustable volume slider
- [ ] Stop-all-sounds button
- [ ] Per-sound volume settings
- [ ] Support for MP3 and other audio formats
- [ ] Editable sound labels through the GUI
- [ ] Automatic audio-device discovery
- [ ] Configurable keyboard shortcuts
- [ ] Packaging as a standalone Windows executable
- [ ] Improved transparent overlay and interface customisation

## 📄 License

Choose a licence before distributing the project. The MIT License is a common option for open-source software, provided you are comfortable allowing reuse and redistribution under its terms.

If you use third-party sound clips, make sure you have the necessary rights to redistribute them. Consider keeping copyrighted audio files out of the public repository.

## 👨‍💻 Author

**Jesus**

JASUS 2026 Soundboard

Built with Python, a sense of humour, and a passion for automation.


*Press a key. Make a moment.* 🔊
