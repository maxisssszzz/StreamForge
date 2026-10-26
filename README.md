# StreamForge

StreamForge is a local web interface for [yt-dlp](https://github.com/yt-dlp/yt-dlp). The HTML page uses a small Python companion server to inspect media URLs and run real downloads; opening the HTML file by itself will not start downloads.

Copyright (c) 2026 Maxis. StreamForge-authored code is licensed under GPL-3.0; see [LICENSE](LICENSE). yt-dlp is a separate dependency and retains its own license.

## Requirements

- Python 3.10 or newer
- yt-dlp installed and available on `PATH`
- FFmpeg for merging separate video/audio streams, audio conversion, trimming, metadata embedding, and GIF output
- A supported JavaScript runtime (such as Deno) for full YouTube support; see the [yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

Install yt-dlp and its recommended Python dependencies:

```powershell
python -m pip install -U "yt-dlp[default]"
```

You can instead download the recommended Windows release binary (`yt-dlp.exe`) from the [yt-dlp release files](https://github.com/yt-dlp/yt-dlp#release-files) and add it to `PATH` or place it next to `streamforge_server.py`.

## Start the interface

From this folder, run:

```powershell
python .\streamforge_server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. Keep the terminal open while using StreamForge; press `Ctrl+C` there to stop the server.

## Windows executable

The v0.1 packaged Windows build is `dist\StreamForge-v0.1.exe`. Run it to start the local server and open StreamForge in your browser; keep its console window open while using the app and press `Ctrl+C` to stop it. The executable bundles the interface and yt-dlp, so Python and a separate yt-dlp installation are not required.

FFmpeg is still required for merging separate streams, audio conversion, trimming, metadata embedding, and GIF output. Install FFmpeg and make it available on `PATH` (or install the Gyan build with winget, which StreamForge can locate). Some sites, including YouTube, may also require a supported JavaScript runtime such as Deno; see the [yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

## Build from source

Install Python 3.10 or newer, the pinned yt-dlp build dependency, and PyInstaller, then build from the repository root:

```powershell
python -m pip install "yt-dlp[default]==2026.10.21" "pyinstaller==6.22.3"
pyinstaller --noconfirm .\StreamForge.spec
```

## Use

1. Paste a public media URL and select **Fetch** to load its actual title, duration, and available media details.
2. Choose video, audio, or GIF output and adjust the options.
3. On first run, choose a save folder. The default is `%USERPROFILE%\Downloads`; the choice is remembered in `%LOCALAPPDATA%\StreamForge\settings.json` and can be changed with **Save location**. Select **Start Download** to run yt-dlp and save the completed file there. Output filenames include their selected quality or audio/GIF settings, so different downloads of the same media do not get mistaken for an older file.

The server listens only on `127.0.0.1`, rejects local/private network URLs, and accepts requests only from its local interface. Media is written to disk and streamed to the browser; StreamForge does not keep the media bytes in an in-memory download cache. Temporary job references are released after the file is streamed. Downloads may require FFmpeg and a JavaScript runtime depending on the chosen output and source site. Only download content you have permission to use.

## Release channels and updates

For a release binary, `yt-dlp -U` updates the current channel. The official README describes `stable`, `nightly`, and `master`; regular users are recommended to use `nightly` for newer site fixes:

```powershell
yt-dlp --update-to nightly
```

For pip installations, update with:

```powershell
python -m pip install -U "yt-dlp[default]"
```

To install/update the nightly pre-release through pip:

```powershell
python -m pip install -U --pre "yt-dlp[default]"
```

See the official [release files and update instructions](https://github.com/yt-dlp/yt-dlp#release-files) for platform-specific downloads, verification, alternate builds, and complete channel details.
