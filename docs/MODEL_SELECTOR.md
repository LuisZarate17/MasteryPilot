# Model Selector Utility

## Overview

The repository includes a separate Windows desktop utility for updating the local model selection used by the AI Tutor system.

Project path:

- `model_selector_app/ModelSelector/ModelSelector`

## Purpose

This tool helps an operator choose a Hugging Face model and write the selected model ID into a `.env` file as:

```env
LANGUAGE_MODEL_ID="chosen-model-id"
```

## Technology

- .NET 8
- Windows Forms
- HtmlAgilityPack
- HtmlAgilityPack.CssSelectors

## What the utility does

1. Loads a Windows Forms interface.
2. Scrapes trending Hugging Face text-generation model pages.
3. Displays model name, parameter count, last updated value, and download count.
4. Prompts the operator to choose a `.env` file.
5. Writes the selected `LANGUAGE_MODEL_ID` value into that file.

## Operational Notes

- This is an operator tool, not a client-facing feature.
- It depends on live access to Hugging Face model listing pages.
- It is Windows-only because it targets `net8.0-windows` and uses Windows Forms.
- It overwrites the selected `.env` file contents with a single `LANGUAGE_MODEL_ID` line in the current implementation.

## Usage Guidance

### Typical workflow

1. Build and run the Windows Forms application.
2. Wait for model data to load.
3. Load the target `.env` file from the File menu.
4. Select a model from the list.
5. Click Apply.
6. Restart the Django application if needed so the new configuration is used.

### Caution

Because the current implementation writes the entire file contents with one line, operators should:

- Back up the target `.env` file first.
- Avoid pointing the tool at a multi-setting environment file unless this behavior is acceptable.

## When to Use It

Use this utility when:

- The deployment relies on local model selection through `LANGUAGE_MODEL_ID`.
- An operator needs a simple desktop workflow to change the selected model.

Do not use it as the only source of deployment configuration truth. Environment management should still be documented and controlled operationally.
