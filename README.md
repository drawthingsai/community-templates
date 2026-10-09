# Community Templates

This repository maintains the starter templates for the project ideas in Local Code. When onboarding finishes, Local Code creates a project for each idea left on and copies the matching template into it.

## Layout

Each template is a folder under `./templates` named exactly after the English title of its project idea. Everything inside the folder is copied into the new project, keeping its layout.

```
templates/
└── File Organizer/
    └── AGENTS.md
```

The project ideas in Local Code are:

* File Organizer
* House Chores
* Daily Brief
* Tax Proofread
* Graphic Novelist
* Explainer Videos
* Office Work

An idea without a template starts as an empty project.

## How to Contribute

To contribute to a template, please follow these steps:

 1. **Find or Create the Template Folder**: Use the English title of the project idea as the folder name under `./templates`.
 2. **Add an `AGENTS.md`**: Describe what the project is for and how the agent should work in it.
 3. **Add Supporting Files**: Optionally include scripts, examples, or other files the project should start with.
 4. **Add Project Skills**: Optionally put skills in `.agents/skills/<name>/SKILL.md`. Local Code discovers them for the project, and their scripts run from the project folder.
 5. **Add a Preview Video**: Optionally add `.template.json` with `{"preview": "preview.mp4"}` (a video in the template) or `{"preview": "https://..."}` (a hosted video). Local Code shows a Preview button in the project that plays it.

### Publishing

On every push to `main`, a workflow zips the contents of each template folder and publishes the zips to [templates.drawthings.ai](https://templates.drawthings.ai) from the `json` branch, so `templates/File Organizer` is served as `File%20Organizer.zip`. Local Code downloads the zip of each idea left on and extracts it into the new project.

## Licensing

Templates are licensed under the MIT License. See [LICENSE](LICENSE).
