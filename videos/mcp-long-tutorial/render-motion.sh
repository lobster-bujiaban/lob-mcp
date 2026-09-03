#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/motion"
npx --yes hyperframes@0.7.108 check
npx --yes hyperframes@0.7.108 render --output ../lob-mcp-motion.raw.mp4
cd "$ROOT"
ffmpeg -y -i lob-mcp-motion.raw.mp4 \
  -i assets/voice/01.mp3 -i assets/voice/02.mp3 -i assets/voice/03.mp3 -i assets/voice/04.mp3 \
  -i assets/voice/05.mp3 -i assets/voice/06.mp3 -i assets/voice/07.mp3 -i assets/voice/08.mp3 \
  -i assets/voice/09.mp3 -i assets/voice/10.mp3 -i assets/voice/11.mp3 -i assets/voice/12.mp3 \
  -i assets/voice/13.mp3 \
  -filter_complex "[1:a][2:a][3:a][4:a][5:a][6:a][7:a][8:a][9:a][10:a][11:a][12:a][13:a]concat=n=13:v=0:a=1[narration];[0:v]subtitles=captions.vtt:force_style='FontName=Heiti SC,FontSize=9,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,Outline=1,Shadow=0,MarginL=90,MarginR=90,MarginV=50,Alignment=2'[video]" \
  -map "[video]" -map "[narration]" -c:v libx264 -preset medium -crf 19 -c:a aac -b:a 160k \
  -shortest lob-mcp-long-tutorial.mp4
