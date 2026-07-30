# Quick reference: bash one-liners

Bash one-liners I keep forgetting: find . -name "*.py" -exec wc -l {}+ to count lines in Python files. history | awk '{print $2}' | sort | uniq -c | sort -rn | head to see most-used commands. ffmpeg -i input.mp4 -vf scale=1280:720 output.mp4 to resize a video.