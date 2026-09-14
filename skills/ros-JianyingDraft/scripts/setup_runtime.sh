#!/bin/bash
set -euo pipefail
runtime="${JDC_RUNTIME:-$HOME/.cache/ros-JianyingDraft/venv}"
command -v ffprobe >/dev/null || { echo 'ffprobe required; install FFmpeg first.' >&2; exit 2; }
if [ ! -x "$runtime/bin/python" ]; then python3 -m venv "$runtime"; fi
"$runtime/bin/python" -m pip install 'pyjianyingdraft @ git+https://github.com/GuanYixuan/pyJianYingDraft.git@c3318066d964744e2bfc66f75c71745fe8cea52a' 'pymediainfo==7.0.1' 'imageio==2.37.4' 'pillow==12.3.0'
"$runtime/bin/python" -c 'from pymediainfo import MediaInfo; import pyJianYingDraft; assert MediaInfo.can_parse(), "MediaInfo runtime unavailable"'
printf 'Runtime ready: %s/bin/python\n' "$runtime"
