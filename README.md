# MINECRAFT OFFICIAL DOWNLOADER

A Python desktop application for downloading official Minecraft Java Edition version files from Mojang's official metadata.

## Features

- Fetch Minecraft version metadata from Mojang's official version manifest.
- Download Minecraft client JAR files.
- Verify downloaded files using SHA-1 hashes and file sizes.
- Support HTTP(S) proxy configuration.
- Provide a PySide6 graphical interface.
- Help protect existing files when downloads fail.

## Requirements

- Python 3.11 or a compatible Python version.
- PySide6.

## Run from Source

1. Clone or download this repository.
2. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the application:

   ```bash
   python mc_gui_qt.py
   ```

## Testing

Run the logic tests with:

```bash
python test_logic.py
```

The tests access Mojang's official servers and may download test files.

## Disclaimer

This is an independent community project and is not affiliated with, endorsed by, or sponsored by Mojang Studios or Microsoft.

Minecraft is a trademark of Mojang Studios and Microsoft. All rights to Minecraft and its associated assets belong to their respective owners.

## License

See the LICENSE file for the applicable license.
