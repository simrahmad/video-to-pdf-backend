from flask import Flask, request, jsonify
import yt_dlp
import whisper
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import yagmail
import os

app = Flask(__name__)

# Load Whisper model
print("Loading Whisper model... This may take a minute...")
model = whisper.load_model("base")
print("Model loaded successfully!")

@app.route("/convert", methods=["POST"])
def convert_video():
    data = request.json
    video_url = data.get("video_url")
    email = data.get("email")
    
    if not video_url or not email:
        return jsonify({"status": "error", "message": "Video URL or email missing"}), 400

    try:
        print(f"Processing video: {video_url}")
        
        # 1️⃣ Download audio from video
        print("Downloading audio...")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "audio.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        audio_file = "audio.mp3"
        print("Audio downloaded successfully!")

        # 2️⃣ Convert speech to text using Whisper
        print("Transcribing audio to text...")
        result = model.transcribe(audio_file)
        text = result["text"]
        print(f"Transcription complete! Length: {len(text)} characters")

        # 3️⃣ Create PDF from text
        print("Creating PDF...")
        pdf_file = "output.pdf"
        
        print(f"Original text length: {len(text)} characters")
        print(f"First 100 chars: {text[:100]}")  # Debug
        
        # Better text cleaning
        clean_text = text.replace('\x00', '')
        clean_text = clean_text.strip()
        
        if not clean_text:
            clean_text = "Error: No text could be extracted from the video."
            print("WARNING: Extracted text was empty!")
        
        print(f"Cleaned text length: {len(clean_text)} characters")
        
        # Create PDF with ReportLab
        doc = SimpleDocTemplate(pdf_file, pagesize=letter,
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        story = []
        
        # Add title
        title = Paragraph("<b>Video Transcript</b>", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 30))
        
        # Format text for ReportLab
        formatted_text = clean_text.replace('\n', '<br/>')
        formatted_text = formatted_text.replace('&', '&amp;')
        formatted_text = formatted_text.replace('<', '&lt;')
        formatted_text = formatted_text.replace('>', '&gt;')
        formatted_text = formatted_text.replace('<br/>', '<br/>')
        
        # Add transcribed text
        para = Paragraph(formatted_text, styles['Normal'])
        story.append(para)
        
        doc.build(story)
        print(f"PDF created successfully!")

        # 4️⃣ Send email with PDF attachment
        print(f"Sending email to {email}...")
        yag = yagmail.SMTP("simrahahmad@gmail.com", "ynggciubjxnhelcn")
        yag.send(
            to=email,
            subject="Your Video Transcript PDF",
            contents="Here is your PDF transcript from the video.",
            attachments=pdf_file
        )
        print("Email sent successfully!")

        # 5️⃣ Clean up files
        os.remove(audio_file)
        os.remove(pdf_file)

        return jsonify({"status": "success", "message": "PDF sent to email successfully!"})

    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "success", "message": "Backend is running!"})

if __name__ == "__main__":
    print("Starting Flask server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)