#!/bin/bash

# Prevent MSYS path conversion on Windows (Git Bash) for PyInstaller semicolon flags
export MSYS_NO_PATHCONV=1

# Unset conflicting Python environment variables
unset PYTHONHOME
unset PYTHONPATH

# Remove any old builds
rm -rf build dist

echo "Building PDF Parser Light with PyInstaller..."

# Build the application
# --windowed creates a macOS .app bundle
# --noconsole prevents the terminal window from popping up
# --icon bundles the icon
# Detect Operating System
OS_NAME="$(uname -s 2>/dev/null || echo "Unknown")"

# Configure platform-specific PyInstaller parameters
# (Icon and data flags are configured in the PyInstaller step below)

# Dynamic Python interpreter discovery (find first environment with PyInstaller installed)
CANDIDATES=()
[ -n "$VIRTUAL_ENV" ] && CANDIDATES+=("$VIRTUAL_ENV/bin/python" "$VIRTUAL_ENV/Scripts/python.exe")
[ -f "venv/bin/python" ] && CANDIDATES+=("venv/bin/python")
[ -f "venv/Scripts/python.exe" ] && CANDIDATES+=("venv/Scripts/python.exe")
[ -f "$HOME/miniforge3/bin/conda" ] && CANDIDATES+=("$HOME/miniforge3/bin/conda run -n base python")
[ -f "$HOME/miniconda3/bin/conda" ] && CANDIDATES+=("$HOME/miniconda3/bin/conda run -n base python")
[ -f "$HOME/anaconda3/bin/conda" ] && CANDIDATES+=("$HOME/anaconda3/bin/conda run -n base python")
[ -f "/opt/homebrew/bin/python3" ] && CANDIDATES+=("/opt/homebrew/bin/python3")
CANDIDATES+=("python3" "python" "py")

CMD=""
for candidate in "${CANDIDATES[@]}"; do
    if $candidate -m PyInstaller --version &>/dev/null; then
        CMD="$candidate"
        break
    fi
done

if [ -z "$CMD" ]; then
    echo "Error: PyInstaller not found in any Python environment. Install it via 'pip install pyinstaller'."
    exit 1
fi

echo "Detected Platform: $OS_NAME"
echo "Using Python environment: $CMD"

# Build execution according to target platform conventions
if [[ "$OS_NAME" == "Darwin"* ]]; then
    $CMD -m PyInstaller --noconsole --windowed \
        --name "PDF Parser Light" \
        --icon=icon.icns \
        --add-data "icon.png:." \
        --add-data "icon.icns:." \
        --collect-all customtkinter \
        --collect-all tkinterdnd2 \
        app_launcher.py
elif [[ "$OS_NAME" == "MINGW"* ]] || [[ "$OS_NAME" == "MSYS"* ]] || [[ "$OS_NAME" == "CYGWIN"* ]]; then
    $CMD -m PyInstaller --noconsole --onefile \
        --name "PDF Parser Light" \
        --icon=icon.ico \
        --add-data "icon.png;." \
        --add-data "icon.ico;." \
        --collect-all customtkinter \
        --collect-all tkinterdnd2 \
        app_launcher.py
else
    # Linux / Unix
    $CMD -m PyInstaller --noconsole --onefile \
        --name "PDF Parser Light" \
        --icon=icon.png \
        --add-data "icon.png:." \
        --collect-all customtkinter \
        --collect-all tkinterdnd2 \
        app_launcher.py
fi

# Fix customtkinter assets path inside macOS app bundle if needed
if [[ "$OS_NAME" == "Darwin"* ]] && [ -d "dist/PDF Parser Light.app/Contents/Resources/customtkinter/assets" ]; then
    echo "Ensuring customtkinter assets exist in Frameworks directory..."
    mkdir -p "dist/PDF Parser Light.app/Contents/Frameworks/customtkinter"
    cp -r "dist/PDF Parser Light.app/Contents/Resources/customtkinter/assets" "dist/PDF Parser Light.app/Contents/Frameworks/customtkinter/"
fi

# Codesign the bundle on macOS (optional/ad-hoc for local run permissions)
if [[ "$OS_NAME" == "Darwin"* ]] && [ -d "dist/PDF Parser Light.app" ]; then
    echo "Signing macOS app bundle..."
    codesign --force --deep --sign - "dist/PDF Parser Light.app"
fi

echo "Success! Application created in the 'dist' directory."