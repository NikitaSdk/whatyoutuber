# WhatYouTuber

**Turns a whole YouTube channel into a folder of texts.** Scan a channel, pick videos, and get transcripts, slide text and an index you can search.

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-FF0000?logo=youtube&logoColor=white)
![Tesseract](https://img.shields.io/badge/Tesseract-OCR-5A5A5A)
![Tkinter](https://img.shields.io/badge/Tkinter-GUI-3776AB)

## Features

- **Channel catalog:** scans all videos; a re-scan merges new videos into the saved catalog.
- **Transcription:** uses the [video-to-text](https://github.com/NikitaSdk/video-to-text) converter (Whisper).
- **Slides without downloading video:** grabs frames from the stream, drops duplicates by perceptual hash, recognises text with Tesseract (formulas optionally with pix2tex).
- **Search and filters** that understand Russian word forms (pymorphy3).
- **Export:** links, titles, CSV list, table of contents and one combined file.

## Structure

```
core/    catalog, scanner, frames, OCR, search, export, queue
ui/      Tkinter tabs: channel, search, convert, results
tests/   unit tests
```

## Run

```bash
pip install -r requirements.txt   # plus Tesseract with rus + eng languages
python main.py
```
