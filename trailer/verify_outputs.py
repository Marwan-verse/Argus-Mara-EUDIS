"""Check deliverable metadata and decode both exported videos end to end."""
import json
import subprocess
import wave
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN = ROOT / 'node_modules' / '@remotion' / 'compositor-win32-x64-msvc'
results = []
for filename, seconds, frames in [('argus-mara-application-60s.mp4', 60, 1800), ('argus-mara-application-30s.mp4', 30, 900)]:
    path = ROOT / 'out' / filename
    info = json.loads(subprocess.check_output([str(BIN/'ffprobe.exe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height']) == (1920, 1080)
    assert video['r_frame_rate'] == '30/1'
    assert video['codec_name'] == 'h264' and audio['codec_name'] == 'aac'
    assert abs(float(info['format']['duration']) - seconds) < .1
    assert int(video['nb_frames']) == frames
    subprocess.run([str(BIN/'ffmpeg.exe'), '-v', 'error', '-xerror', '-i', str(path), '-c:v', 'rawvideo', '-c:a', 'pcm_s16le', '-f', 'null', '-'], check=True)
    decoded = ROOT / 'out' / 'instrumental-check.wav'
    subprocess.run([str(BIN/'ffmpeg.exe'), '-v', 'error', '-y', '-i', str(path), '-vn', '-c:a', 'pcm_s16le', '-ar', '44100', str(decoded)], check=True)
    def samples(wav_path):
        with wave.open(str(wav_path)) as wav:
            return np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(float)
    actual = samples(decoded)
    expected = samples(ROOT / 'public' / ('short-soundtrack.wav' if seconds == 30 else 'film-soundtrack.wav'))
    count = min(len(actual), len(expected))
    correlation = float(np.corrcoef(actual[:count], expected[:count])[0, 1])
    assert correlation > .99, ('Audio differs from instrumental source', correlation)
    print('Instrumental source correlation:', round(correlation, 6), flush=True)
    results.append({'file': filename, 'duration_seconds': seconds, 'frames': frames, 'resolution': '1920x1080', 'fps': 30, 'video': 'H.264', 'audio': 'AAC', 'bytes': path.stat().st_size, 'full_decode': 'passed'})
    print(filename, 'metadata and full decode passed', flush=True)
(ROOT/'out'/'verification.json').write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
