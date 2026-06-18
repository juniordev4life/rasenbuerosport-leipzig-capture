"""Encoder-Wahl fuer Clips + Reel: VA-API H.264 (Hardware) wenn ein Render-Node
existiert (NUC, ~4x Echtzeit, wichtig fuer 60fps), sonst libx265 (Software,
Dev-Mac). Drei Bausteine, an jeder Encode-Stelle gleich benutzt:

  device_args()  -> globale ffmpeg-Args VOR den Inputs (`-vaapi_device ...`)
  prep_filter()  -> letztes Filter-Glied, das den Frame fuer den Encoder fertig
                    macht (VA-API: auf die GPU laden; libx265: yuv420p)
  codec_args()   -> die `-c:v ...`-Args

Per Env steuerbar:
  REEL_ENCODER   auto (Default) | vaapi | libx265
  VAAPI_DEVICE   Render-Node (Default /dev/dri/renderD128)
  REEL_BITRATE   VA-API-Zielbitrate (Default 8M; 60fps will mehr als 30fps)
"""
import os

VAAPI_DEVICE = os.environ.get("VAAPI_DEVICE", "/dev/dri/renderD128")
_BITRATE = os.environ.get("REEL_BITRATE", "8M")
_MODE = os.environ.get("REEL_ENCODER", "auto")


def use_vaapi():
    """True -> VA-API-Hardware-Encode. auto: an, wenn der Render-Node existiert."""
    if _MODE == "vaapi":
        return True
    if _MODE == "libx265":
        return False
    return os.path.exists(VAAPI_DEVICE)


def device_args():
    """ffmpeg-Args VOR den Inputs (VA-API-Geraet) — bei libx265 leer."""
    return ["-vaapi_device", VAAPI_DEVICE] if use_vaapi() else []


def prep_filter():
    """Letztes Filter-Glied vor dem Encoder. VA-API: nach NV12 wandeln + auf die
    GPU laden; libx265: yuv420p (Alpha weg, kompatibles Pixelformat)."""
    return "format=nv12,hwupload" if use_vaapi() else "format=yuv420p"


def codec_args():
    """`-c:v ...`-Args fuer den gewaehlten Encoder."""
    if use_vaapi():
        return ["-c:v", "h264_vaapi", "-b:v", _BITRATE]
    return ["-c:v", "libx265", "-preset", "medium", "-crf", "28", "-tag:v", "hvc1"]
