# Explainer Videos

This project makes short videos that explain things. Keep each video's prompts,
specs, source images, and outputs in this project folder, and show the user the
finished video.

## Choose the approach

- **A person on camera:** to make a photo of one or more people speak, such as a
  presenter, a trip recap, a greeting, or "make this photo talk", use the
  `talking-head-video` skill in `.agents/skills`. It writes or takes the dialogue,
  animates the photo with synchronized speech, and adds a title card and captions.
  With no photo, generate a front-facing portrait first only when the user asks for
  a generated presenter.
- **Motion graphics:** for animated diagrams, text, charts, or slides, use the
  `hyperframes` skill.
- **Generated footage:** for short clips with native sound and no fixed face, use
  MiniMax H3 through the `use-draw-things-cli` skill.

## Content

- Keep explanations accurate. Look up facts for time-sensitive topics, such as news,
  prices, or weather, and use only what the user gave or what you found.
- Keep spoken lines short and natural; on-screen text should match what is said.
- Only animate real people's photos when the user says it is them or they have
  agreed to it.
