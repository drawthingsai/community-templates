#!/usr/bin/env python3
"""Plan and compose a talking-head video from a photo and a JSON spec.

Plan once, then run each stage from the copy that plan places in the work folder:
  python3 talking_head.py plan SPEC --work DIR
  python3 DIR/talking_head.py estimate|avatar|compose|all|check

plan validates the spec, prepares DIR/portrait.png, and writes DIR/plan.json and
DIR/avatar_prompt.txt. Stages call draw-things-cli and html2video, keep outputs that
already exist (set FORCE=1 to redo), and read only DIR/plan.json, so plan again after
editing the spec.
"""

import argparse
import html
import json
import math
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys

# MiniMax H3 first-frame animation: voices and lip motion are generated together.
MODEL = "minimax_h3_fl2va_i8x.ckpt"
FPS = 24
MAX_FRAMES = 362  # about 15 s; frame counts must be 17k + 5
WORDS_PER_SECOND = 2.8  # measured on MiniMax H3 renders

# Output sizes by quality and photo orientation. "small" stays within a free plan's
# 40,000 compute units per request for clips up to 209 frames (8.7 s).
SIZES = {
    "small": {"portrait": (256, 320), "landscape": (320, 256), "square": (256, 256)},
    "standard": {"portrait": (512, 640), "landscape": (640, 512), "square": (512, 512)},
    "high": {"portrait": (768, 960), "landscape": (960, 768), "square": (768, 768)},
}

DEFAULTS = {
    "backend": "cloud",
    "quality": "standard",
    "rotate": 0,
    "avatar_prompt": None,
    "speaker": "a warm, clear, conversational voice",
    "language": "English",
    "soundscape": "Clear close-microphone speech with soft natural ambience.",
    "seed": 42,
    "captions": True,
    "title": None,
    "subtitle": None,
    "output": "talking_head.mp4",
}


class SpecError(Exception):
    pass


def png_size(path):
    with open(path, "rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SpecError(f"Not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def ffmpeg(*args):
    """Run the bundled ffmpeg. shutil.which cannot see built-in shell commands."""
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)
    except FileNotFoundError:
        raise SpecError("ffmpeg is not available; supply a PNG or JPEG photo.")


def prepare_image(src, dst, rotate):
    """Write an upright RGB PNG no larger than 1280 px on its long side.

    Draw Things reads raw PNG pixels and ignores orientation metadata, so orientation
    is applied to the pixels: Pillow handles JPEG and PNG (EXIF), ffmpeg handles HEIC
    (rotation and mirroring). "rotate" adds clockwise degrees for photos that still
    come out sideways.
    """
    try:
        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        image = image.rotate(-rotate, expand=True) if rotate else image
        image.thumbnail((1280, 1280))
        image.save(dst)
        return
    except ImportError:
        pass
    except Exception as error:  # Pillow cannot decode HEIC.
        print(f"Pillow could not read {src} ({error}); converting with ffmpeg.", file=sys.stderr)
    full = dst + ".full.png"
    # HEIC decodes through a tile grid that cannot take a filter, so scale separately.
    ffmpeg("-i", src, "-frames:v", "1", full)
    turns = {0: [], 90: ["transpose=1"], 180: ["transpose=1", "transpose=1"], 270: ["transpose=2"]}
    ffmpeg("-i", full, "-vf", ",".join(
        ["scale=1280:1280:force_original_aspect_ratio=decrease"] + turns[rotate]), dst)
    os.remove(full)


def word_budget(frames):
    return max(0, int((frames / FPS - 1.2) * WORDS_PER_SECOND))


def load_spec(path, portrait=None):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    spec = {**DEFAULTS, **raw}
    spec["image"] = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)),
                                                  spec.get("image") or ""))
    if not os.path.isfile(spec["image"]):
        raise SpecError(f"'image' must name an existing photo: {spec['image']}")
    if spec["backend"] not in ("cloud", "local"):
        raise SpecError("backend must be 'cloud' or 'local'.")
    if spec["quality"] not in SIZES:
        raise SpecError(f"quality must be one of {sorted(SIZES)}.")
    if spec["rotate"] not in (0, 90, 180, 270):
        raise SpecError("rotate must be 0, 90, 180, or 270 (clockwise degrees).")

    if spec.get("dialogue"):
        # A list of {"speaker": who is on screen, "voice": how they sound, "line": words}.
        if spec.get("script"):
            raise SpecError("Use either 'dialogue' or 'script', not both.")
        if not all(turn.get("speaker") and turn.get("line") for turn in spec["dialogue"]):
            raise SpecError("Each dialogue turn needs 'speaker' and 'line'.")
        spec["script"] = " ".join(turn["line"].strip() for turn in spec["dialogue"])
    if not spec.get("script"):
        raise SpecError("Provide 'dialogue' or 'script'.")

    if "frames" not in raw:
        # Smallest valid frame count covering the speech, plus a breath and a closing beat.
        seconds = len(spec["script"].split()) / WORDS_PER_SECOND + 1.2
        spec["frames"] = 17 * max(0, math.ceil((seconds * FPS - 5) / 17)) + 5
        if spec["frames"] > MAX_FRAMES:
            raise SpecError(f"The dialogue needs about {seconds:.0f} s; clips max out near 15 s "
                            f"(about {word_budget(MAX_FRAMES)} words). Shorten it or split it.")
    elif not (5 <= spec["frames"] <= MAX_FRAMES and (spec["frames"] - 5) % 17 == 0):
        raise SpecError(f"frames must be 17k + 5 in 5...{MAX_FRAMES}.")

    if "width" not in raw or "height" not in raw:
        shape = "portrait"
        if portrait and os.path.isfile(portrait):
            w, h = png_size(portrait)
            shape = "square" if abs(w / h - 1) < 0.12 else ("landscape" if w > h else "portrait")
        spec["width"], spec["height"] = SIZES[spec["quality"]][shape]
    if spec["width"] % 64 or spec["height"] % 64:
        raise SpecError("width and height must be multiples of 64.")
    return spec


def minimax_prompt(spec):
    demeanor = spec["avatar_prompt"] or (
        "Everyone keeps the same framing, blinks naturally, and uses small, natural head "
        "movements; the camera is static.")
    if spec.get("dialogue"):
        # Stable speaker IDs by first appearance; each voice is described once.
        ids = {}
        turns = []
        for turn in spec["dialogue"]:
            who = turn["speaker"]
            voice = ""
            if who not in ids:
                ids[who] = f"S{len(ids) + 1}"
                voice = f", with {turn['voice']}," if turn.get("voice") else ""
            lead = "Then " if turns else ""
            line = " ".join(turn["line"].split())
            turns.append(f"{lead}{who} ({ids[who]}){voice} says: <d>[{spec['language']}] {line}</d>")
        speech = " ".join(turns)
        ending = "After the last line, they hold relaxed smiles."
    else:
        script = " ".join(spec["script"].split())
        speech = (f"The person (S1), with {spec['speaker']}, looks into the lens and says: "
                  f"<d>[{spec['language']}] {script}</d>")
        ending = "After the line, they hold a relaxed smile."
    return f"""For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Everyone from <Picture 1> stays in the same framing, clothing, lighting, and background. {speech} {demeanor} {ending}

overall_soundscape: {spec["soundscape"]}

non_diegetic_music: None.
"""


def draw_things_command(spec, work):
    command = [os.environ.get("DRAW_THINGS_CLI", "draw-things-cli"), "generate"]
    if spec["backend"] == "cloud":
        command.append("--cloud-compute")
    command += [
        "--model", MODEL, "--image", os.path.join(work, "portrait.png"),
        "--prompt-file", os.path.join(work, "avatar_prompt.txt"),
        "--frames", str(spec["frames"]), "--width", str(spec["width"]),
        "--height", str(spec["height"]), "--seed", str(spec["seed"]), "--disable-preview",
    ]
    return command + shlex.split(os.environ.get("DT_FLAGS", ""))


def run(command):
    """Run a bundled command, streaming its output; fail with its exit status."""
    try:
        status = subprocess.run(command).returncode
    except FileNotFoundError:
        raise SpecError(f"{command[0]} is not available in the current environment.")
    if status != 0:
        raise SpecError(f"{os.path.basename(command[0])} exited with status {status}.")


def skip(path):
    if os.path.isfile(path) and os.path.getsize(path) > 0 and not os.environ.get("FORCE"):
        print(f"skip: {path} exists (set FORCE=1 to redo)")
        return True
    return False


def mp4_duration(path, track=b"vide"):
    """A track's duration in seconds, from its mdhd box, without external tools."""
    with open(path, "rb") as f:
        data = f.read()

    def boxes(start, end):
        while start + 8 <= end:
            size, kind = struct.unpack(">I4s", data[start:start + 8])
            header = 8
            if size == 1:
                size, header = struct.unpack(">Q", data[start + 8:start + 16])[0], 16
            size = size or end - start
            yield kind, start + header, start + size
            start += size

    def child(start, end, name):
        return next(((b, e) for kind, b, e in boxes(start, end) if kind == name), None)

    moov = child(0, len(data), b"moov")
    for kind, body, end in boxes(*moov) if moov else []:
        mdia = kind == b"trak" and child(body, end, b"mdia")
        hdlr = mdia and child(*mdia, b"hdlr")
        if hdlr and data[hdlr[0] + 8:hdlr[0] + 12] == track:
            b = child(*mdia, b"mdhd")[0]
            if data[b] == 1:
                timescale, duration = struct.unpack(">IQ", data[b + 20:b + 32])
            else:
                timescale, duration = struct.unpack(">II", data[b + 12:b + 20])
            return duration / timescale
    return None


def caption_cues(text, duration):
    """Short cues timed by character count. Approximate: no forced alignment."""
    cues = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = sentence.split()
        cues += [" ".join(words[i:i + 8]) for i in range(0, len(words), 8)]  # two lines max
    total = float(sum(len(c) + 4 for c in cues)) or 1.0
    t, timed = 0.0, []
    for cue in cues:
        span = duration * (len(cue) + 4) / total
        timed.append({"start": round(t, 3), "end": round(t + span, 3), "text": cue})
        t += span
    return timed


def write_composition(spec, work, duration):
    out_dir = os.path.join(work, "compose")
    os.makedirs(out_dir, exist_ok=True)
    shutil.copyfile(os.path.join(work, "avatar.mp4"), os.path.join(out_dir, "avatar.mp4"))
    # Time captions to the estimated speech, not the closing beat.
    speech = min(duration, len(spec["script"].split()) / WORDS_PER_SECOND + 0.6)
    cues = caption_cues(spec["script"], speech) if spec["captions"] else []
    # Render overlays at a size where text stays crisp.
    scale = 2 if max(spec["width"], spec["height"]) <= 320 else 1
    cw, ch = spec["width"] * scale, spec["height"] * scale
    lower_third = ""
    if spec["title"]:
        lower_third = (f'<div id="lt"><div class="t">{html.escape(spec["title"])}</div>'
                       f'<div class="s">{html.escape(spec["subtitle"] or "")}</div></div>')
    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{{margin:0;background:#000;width:{cw}px;height:{ch}px;overflow:hidden;
  font-family:-apple-system,"Helvetica Neue",Arial,sans-serif}}
video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
#lt{{position:absolute;left:{cw * 0.05:.0f}px;top:{ch * 0.07:.0f}px;padding:10px 18px;
  background:rgba(12,12,16,.72);border-left:6px solid #f5b83d;color:#fff;opacity:0}}
#lt .t{{font-size:{ch * 0.05:.0f}px;font-weight:700}}
#lt .s{{font-size:{ch * 0.032:.0f}px;opacity:.8;margin-top:2px}}
#cap{{position:absolute;left:8%;right:8%;bottom:{ch * 0.07:.0f}px;text-align:center;
  font-size:{ch * 0.05:.0f}px;font-weight:600;color:#fff;line-height:1.25;
  text-shadow:0 2px 6px rgba(0,0,0,.9),0 0 2px #000}}
</style></head><body>
<div data-composition-id="main" data-width="{cw}" data-height="{ch}" data-duration="{duration}">
<video src="avatar.mp4" muted playsinline data-start="0" data-duration="{duration}"></video>
<audio src="avatar.mp4" data-start="0" data-duration="{duration}"></audio>
{lower_third}
<div id="cap"></div>
</div>
<script>
const cues = {json.dumps(cues)};
const lt = document.getElementById('lt');
const cap = document.getElementById('cap');
window.html2video = {{
  width: {cw}, height: {ch}, duration: {duration},
  seek(t) {{
    if (lt) {{
      // Fade in over 0.4s at 0.3s, hold, fade out by 4.5s.
      const a = Math.min(1, Math.max(0, (t - 0.3) / 0.4)) * Math.min(1, Math.max(0, (4.5 - t) / 0.4));
      lt.style.opacity = a;
      lt.style.transform = `translateX(${{(1 - a) * -24}}px)`;
    }}
    const cue = cues.find(c => t >= c.start && t < c.end);
    cap.textContent = cue ? cue.text : '';
  }}
}};
</script></body></html>
"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    return out_dir


def stage_estimate(spec, work):
    run(draw_things_command(spec, work) + ["--estimate"])


def stage_avatar(spec, work):
    avatar = os.path.join(work, "avatar.mp4")
    if not skip(avatar):
        run(draw_things_command(spec, work) + ["--video-format", "h264", "--output", avatar])


def stage_compose(spec, work):
    output = os.path.join(work, spec["output"])
    avatar = os.path.join(work, "avatar.mp4")
    if skip(output):
        return
    if not os.path.isfile(avatar):
        raise SpecError("Run the avatar stage first.")
    # Snap to whole frames so html2video emits exactly the avatar's frame count.
    duration = round(mp4_duration(avatar) * FPS) / FPS
    out_dir = write_composition(spec, work, duration)
    run([os.environ.get("HTML2VIDEO", "html2video"), out_dir,
         "--output", output, "--fps", str(FPS), "--json"])


def check(work):
    report = {}
    for name in ("portrait.png", "avatar.mp4", load_plan(work)["output"]):
        path = os.path.join(work, name)
        entry = {"exists": os.path.isfile(path)}
        if entry["exists"] and name.endswith(".png"):
            entry["size"] = list(png_size(path))
        elif entry["exists"]:
            entry["video_seconds"] = round(mp4_duration(path) or 0, 3)
            entry["audio_seconds"] = round(mp4_duration(path, b"soun") or 0, 3)
        report[name] = entry
    print(json.dumps(report, indent=2))


def plan(spec_path, work):
    os.makedirs(work, exist_ok=True)
    work = os.path.abspath(work)
    portrait = os.path.join(work, "portrait.png")
    photo = load_spec(spec_path)
    prepare_image(photo["image"], portrait, photo["rotate"])
    spec = load_spec(spec_path, portrait)
    with open(os.path.join(work, "avatar_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(minimax_prompt(spec))
    # Later stages run this copy, so their commands need no path to the skill.
    if os.path.abspath(__file__) != os.path.join(work, "talking_head.py"):
        shutil.copyfile(os.path.abspath(__file__), os.path.join(work, "talking_head.py"))
    summary = {
        "backend": spec["backend"], "quality": spec["quality"],
        "size": [spec["width"], spec["height"]], "frames": spec["frames"],
        "seconds": round(spec["frames"] / FPS, 2), "words": len(spec["script"].split()),
        "word_budget": word_budget(spec["frames"]), "portrait": portrait,
        "final": os.path.join(work, spec["output"]),
    }
    with open(os.path.join(work, "plan.json"), "w", encoding="utf-8") as f:
        json.dump({**summary, "spec": spec}, f, indent=2)
    print(json.dumps(summary, indent=2))


def load_plan(work):
    path = os.path.join(work, "plan.json")
    if not os.path.isfile(path):
        raise SpecError(f"No plan in {work}; run the plan step first.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["spec"]


STAGES = {"estimate": stage_estimate, "avatar": stage_avatar, "compose": stage_compose}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("spec")
    p.add_argument("--work", required=True)
    # Stages default to the folder holding this script, where plan copies it.
    for name in (*STAGES, "all", "check"):
        sub.add_parser(name).add_argument("--work", default=os.path.dirname(os.path.abspath(__file__)))
    args = parser.parse_args()
    try:
        if args.command == "plan":
            plan(args.spec, args.work)
        elif args.command == "check":
            check(os.path.abspath(args.work))
        else:
            work = os.path.abspath(args.work)
            spec = load_plan(work)
            for name in (["avatar", "compose"] if args.command == "all" else [args.command]):
                STAGES[name](spec, work)
    except (SpecError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
