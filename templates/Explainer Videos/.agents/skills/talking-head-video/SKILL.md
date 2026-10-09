---
name: talking-head-video
description: Turn a photo of one or more people into a short video where they speak, from a conversation the user supplies or one the assistant writes about a topic, finished with a title card and captions. Use for "make this photo talk", talking heads, presenters, avatars, trip or event recaps, greetings, and spokesperson clips. Runs the draw-things-cli step on cloud compute and, when the account cannot cover a request, surfaces the top-up and smaller or local alternatives.
---

# Talking-Head Video

Turn a photo into a speaking video in four steps: write a spec, plan, generate,
then compose. The bundled script does the mechanical work.
Planning copies it into the work folder, so every later step is a short
`python3 th/talking_head.py <stage>` command. Run each command as its own `bash`
call, without `sh` wrappers.

Do not install packages. The script converts HEIC, JPEG, and PNG with the bundled
tools.

## 1. Gather inputs

- **Photo:** resolve the attached or named image to a file path. Ask for a photo
  when none is available; do not substitute a generated one unless the user asks
  for a generated avatar. Then create a front-facing, head-and-shoulders portrait
  with neutral lighting and a closed mouth using the `use-draw-things-cli` skill,
  and use that image.
- **Who is who:** if you can view images, view `th/portrait.png` after planning
  (step 3). Count the people and note what tells them apart, such as clothing,
  hair, hats, or position. If you cannot view images and the user has not said who
  is who, do not stop to ask. Name speakers by position ("the person on the left",
  "the person on the right"), give them neutral voice descriptions ("a friendly,
  relaxed voice"), and say in your reply that they can name who is who for a
  rerun. The user's own description always wins.
- **Conversation:** use the user's words verbatim when they supply them. Otherwise
  write the lines yourself from the topic and what is visible in the photo:
  - Give each visible person one or two short, natural lines in first person, and
    split the lines between them in a sensible order.
  - Stay within the word budget (see step 3). About 20 words in total fits an
    8.7 s clip; 40 words needs about 15 s.
  - Use only facts the user gave or that you looked up. For time-sensitive topics,
    such as today's weather or news, look them up first.
  - Skip filler greetings unless the user asks for them.
  Proceed without asking for approval unless the user wants to review the script;
  say in the reply what the speakers say.

## 2. Write the spec

Create `talking-head.json` in the selected project. Paths are relative to the spec.

```json
{
  "image": "IMG_0074.HEIC",
  "dialogue": [
    {"speaker": "The man in the straw hat", "voice": "a cheerful, relaxed male voice",
     "line": "We just got back from the Eastern Sierra!"},
    {"speaker": "the woman with long dark hair", "voice": "a warm, bright female voice",
     "line": "Endless stars at night, then an onsen soak under the Milky Way."}
  ],
  "soundscape": "Clear speech outdoors by a mountain lake, with a light breeze through autumn leaves.",
  "title": "Eastern Sierra",
  "subtitle": "Stars, lakes & hot springs",
  "output": "eastern_sierra.mp4"
}
```

Spec fields:

- `image` (required): JPEG, PNG, or HEIC.
- `dialogue`: the turns, in order.
  - `speaker` must identify the person by what is visible in the photo.
  - `voice` describes how they sound. Each person's voice is described once, at
    their first turn.
  - Use `script` instead for a single speaker with no turns; `speaker` then
    describes the voice.
- `soundscape`: the ambient sound. Match it to the photo's setting.
- `avatar_prompt`: optional direction for expression, gestures, and camera. Keep
  the camera static unless asked otherwise.
- `title` and `subtitle`: an optional lower-third card. `captions` defaults to true.
- `quality`: `standard` (default), `small`, or `high`. Use `small` when the user
  asks for a cheaper or faster clip.
- `backend`: `cloud` (default) or `local`.
- `rotate`: 0, 90, 180, or 270 clockwise degrees, for a photo that still comes out
  sideways after planning.
- `width`, `height`, and `frames` override the automatic choices. Frames must be
  `17k + 5`, at most 362. `language` sets the dialogue language tag (default
  English).

## 3. Plan and check the portrait

```sh
python3 .agents/skills/talking-head-video/scripts/talking_head.py plan talking-head.json --work th
```

Planning does the following:

- Converts the photo to an upright PNG at `th/portrait.png`, applying its EXIF
  orientation to the pixels.
- Picks the output size from the photo's orientation and `quality`.
- Sizes the clip from the word count.
- Writes `th/avatar_prompt.txt` and `th/plan.json`, and copies the script to
  `th/talking_head.py`.

It prints `size`, `frames`, `seconds`, `words`, and `word_budget`.

Run it from the project folder, where this skill lives under `.agents/skills`.

Then check the result:

- If you can view images, view `th/portrait.png`. If the people are sideways or
  upside down, set `rotate` and plan again; generation uses the raw pixels. If you
  cannot view images, trust the automatic orientation.
- If you had to write a placeholder spec before seeing the photo, update the
  `dialogue` speakers now and plan again. Stages read `th/plan.json`, so plan again
  after any spec edit.
- If planning reports that the dialogue is too long, shorten it. A clip maxes out
  near 15 s.

## 4. Generate

```sh
python3 th/talking_head.py avatar
```

- Run it as one `bash` call with `refresh_sec: 120`. A cloud clip takes about 3–4
  minutes. Follow the waiting guidance in the `use-draw-things-cli` skill.
- Do not check or discuss cost before generating. The account's plan decides what
  a request costs. Requests above the plan's per-request allowance are billed to
  the account's credit balance, when it has one.
- If generation fails because the account cannot cover the request ("insufficient
  balance", or a message that pay-as-you-go is required), the environment offers an
  **Add funds** action. Tell the user, and offer three choices:
  1. Add funds, then rerun this stage at the same quality.
  2. Use a smaller clip: set `"quality": "small"`, keep the dialogue within about
     20 words, plan again, and rerun. `small` at up to 209 frames (8.7 s) fits even
     a free plan's per-request allowance.
  3. Use `"backend": "local"` if the device has, or can download, the model and has
     enough memory. It is slower, and no compute is charged.

  To tell the user how large the request was, run
  `python3 th/talking_head.py estimate`, which prints its compute units without
  generating. Do not quote prices in currency.
- A stage skips work when its output already exists; set `FORCE=1` to redo it.
- If cloud generation reports that the user is not signed in, ask them to sign in
  to their account, then rerun.

## 5. Compose and verify

```sh
python3 th/talking_head.py compose
```

Compose adds the title card and timed captions and exports the final MP4 with
`html2video`.

Then verify the result:

- Run `python3 th/talking_head.py check` to confirm that the video and audio durations
  match.
- View frames near the start, the middle, and each speaker change. Each speaker's
  mouth should move on their own line.
- Deliver the final video from `th/` (the `output` name) using the environment's
  media embedding.

## Exact voice

This skill generates voices with the video. If the user needs a specific recording
or voice reproduced exactly, explain that this skill cannot do that. LongCat-Video-
Avatar with `draw-things-cli generate --avc --audio` lip-syncs to a supplied track,
but only on the local backend.
