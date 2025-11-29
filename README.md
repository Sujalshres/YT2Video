
Hey there! Welcome to the repository for this simple but powerful Python script. This tool is designed to make downloading your favorite YouTube content either the full video or just the sweet, sweet audio as painless as possible.  <br><br>
  
## ⚙ Requirements

Make sure FFmpeg is installed and available in your system’s PATH. As this project heavily uses it. <br> <br>
  
## 🛠️ Troubleshooting Tips

YouTube is always changing things up, and sometimes your downloads might break with an error message. Nine times out of ten, this isn't an issue with this Python script, but with the core library we rely on.  <br><br>
Luckily team behind yt-dlp is super quick to fix such issues. Just run this command inside project folder to update yt-dlp

```bash
pip install --upgrade yt-dlp
```
 <br> 
  
##  Project Dependencies (The Real MVPs)

This tool heavily relies on these awesome open-source projects. They do the heavy lifting of pulling the stream and processing the files. Please show them some love! ❤

- **Yt-dlp**  
This is the core downloader. It handles extracting the video and audio streams from YouTube (and many other sites!). It's a fork of the original youtube-dl and is actively maintained, which is why we rely on it heavily for stability.  
Visit yt-dlp : https://github.com/yt-dlp/yt-dlp

- **FFmpeg**  
Once the raw video and audio streams are downloaded (which often come separately), FFmpeg is the multimedia powerhouse that combines them and converts the output.  
Visit FFmpeg : https://ffmpeg.org/  
  
<br> <br>
  
Made with a little bit of Python magic 🐍 and a lot of help from the open-source community!
