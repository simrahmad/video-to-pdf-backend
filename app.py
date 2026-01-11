from flask import Flask, request, jsonify
import yt_dlp
from vosk import Model, KaldiRecognizer
import wave
import json
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
import yagmail
import os
from werkzeug.utils import secure_filename
import subprocess

app = Flask(__name__)

# Load Vosk model
print("Loading Vosk model...")
MODEL_PATH = "model"
if not os.path.exists(MODEL_PATH):
    print("ERROR: Model not found! Please download vosk-model-small-en-us-0.15")
    print("From: https://alphacephei.com/vosk/models")
    exit(1)

model = Model(MODEL_PATH)
print("Vosk model loaded successfully!")

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def transcribe_audio(audio_file):
    """Transcribe audio using Vosk"""
    try:
        # Convert to WAV 16kHz mono (Vosk requirement)
        wav_file = "temp_audio.wav"
        subprocess.run([
            'ffmpeg', '-i', audio_file,
            '-ar', '16000', '-ac', '1', '-y', wav_file
        ], check=True, capture_output=True)
        
        # Transcribe with Vosk
        wf = wave.open(wav_file, "rb")
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)
        
        transcription = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                if 'text' in result:
                    transcription.append(result['text'])
        
        # Final result
        final_result = json.loads(rec.FinalResult())
        if 'text' in final_result:
            transcription.append(final_result['text'])
        
        wf.close()
        os.remove(wav_file)
        
        full_text = ' '.join(transcription)
        print(f"Transcription: {full_text[:100]}...")
        return full_text
        
    except Exception as e:
        print(f"Transcription error: {str(e)}")
        raise

def process_video_to_pdf(audio_file, email):
    """Common function to process audio and send PDF"""
    try:
        # Convert speech to text using Vosk
        print("Transcribing audio to text...")
        text = transcribe_audio(audio_file)
        print(f"Transcription complete! Length: {len(text)} characters")

        if not text or len(text.strip()) < 10:
            text = "Error: Could not extract meaningful text from the audio. Please ensure the video has clear speech."

        # Create PDF from text
        print("Creating PDF...")
        pdf_file = "output.pdf"
        
        # Clean text
        clean_text = text.replace('\x00', '').strip()
        
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
        print("PDF created successfully!")

        # Send email with PDF attachment
        print(f"Sending email to {email}...")
        gmail_user = os.environ.get("GMAIL_USER", "simrahapp@gmail.com")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "abzqxqsrnavbgvta")
        yag = yagmail.SMTP(gmail_user, gmail_password)
        yag.send(
            to=email,
            subject="Your Video Transcript is Ready! 📄",
            contents="""Hello!

Your video transcript has been successfully converted to PDF.

Please find your PDF document attached to this email.

Thank you for using Video to PDF Converter!

Best regards,
Video to PDF Team
""",
            attachments=pdf_file
        )
        print("Email sent successfully!")

        # Clean up files
        if os.path.exists(audio_file):
            os.remove(audio_file)
        if os.path.exists(pdf_file):
            os.remove(pdf_file)
        
        return True, "PDF sent to email successfully!"
        
    except Exception as e:
        print(f"Error in processing: {str(e)}")
        # Clean up on error
        if os.path.exists(audio_file):
            os.remove(audio_file)
        return False, str(e)

@app.route("/convert", methods=["POST"])
def convert_video():
    """Convert video from URL"""
    data = request.json
    video_url = data.get("video_url")
    email = data.get("email")
    
    if not video_url or not email:
        return jsonify({"status": "error", "message": "Video URL or email missing"}), 400

    try:
        print(f"Processing video: {video_url}")
        
        # Download audio from video with improved YouTube bypass
        print("Downloading audio...")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "audio.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "referer": "https://www.google.com/",
            "http_headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs"],
                    "skip": ["dash", "hls"]
                }
            },
            # Additional options to bypass bot detection
            "geo_bypass": True,
            "age_limit": None,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # Find the downloaded audio file
        audio_file = None
        for ext in ['mp3', 'wav', 'webm', 'm4a']:
            if os.path.exists(f"audio.{ext}"):
                audio_file = f"audio.{ext}"
                break
        
        if not audio_file:
            return jsonify({"status": "error", "message": "Failed to download audio from video"}), 500
        
        print(f"Audio downloaded successfully: {audio_file}")

        # Process and send
        success, message = process_video_to_pdf(audio_file, email)
        
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500

    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
        
        # Check if it's a YouTube bot detection error
        if "Sign in to confirm" in error_msg or "bot" in error_msg.lower():
            return jsonify({
                "status": "error", 
                "message": "YouTube bot protection detected. This video may be restricted. Please try: 1) A different video, 2) Using the Upload feature instead, or 3) Try again in a few minutes."
            }), 500
        
        return jsonify({"status": "error", "message": error_msg}), 500

@app.route("/convert-upload", methods=["POST"])
def convert_upload():
    """Convert uploaded video file"""
    email = request.form.get("email")
    
    if not email:
        return jsonify({"status": "error", "message": "Email missing"}), 400
    
    if 'video' not in request.files:
        return jsonify({"status": "error", "message": "No video file uploaded"}), 400
    
    video_file = request.files['video']
    
    if video_file.filename == '':
        return jsonify({"status": "error", "message": "No video file selected"}), 400
    
    if not allowed_file(video_file.filename):
        return jsonify({"status": "error", "message": "Invalid file type. Allowed: mp4, avi, mov, mkv, webm, flv"}), 400
    
    try:
        print(f"Processing uploaded video: {video_file.filename}")
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(UPLOAD_FOLDER, filename)
        video_file.save(video_path)
        print(f"Video saved to: {video_path}")
        
        # Extract audio from video
        print("Extracting audio...")
        audio_file = "uploaded_audio.mp3"
        
        subprocess.run([
            'ffmpeg', '-i', video_path,
            '-vn', '-acodec', 'libmp3lame',
            '-q:a', '2', audio_file, '-y'
        ], check=True, capture_output=True)
        
        print("Audio extracted successfully!")
        
        # Process and send
        success, message = process_video_to_pdf(audio_file, email)
        
        # Clean up uploaded video
        if os.path.exists(video_path):
            os.remove(video_path)
        
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500
            
    except Exception as e:
        print(f"Error: {str(e)}")
        # Clean up on error
        if 'video_path' in locals() and os.path.exists(video_path):
            os.remove(video_path)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    """Home page with API information"""
    return jsonify({
        "service": "Video to PDF Converter API",
        "version": "1.0",
        "status": "running",
        "endpoints": {
            "/": "API information (this page)",
            "/test": "Test endpoint to check if backend is running",
            "/convert": "POST - Convert YouTube video URL to PDF",
            "/convert-upload": "POST - Convert uploaded video file to PDF"
        },
        "usage": {
            "/convert": {
                "method": "POST",
                "content_type": "application/json",
                "body": {
                    "video_url": "YouTube video URL",
                    "email": "Email address to receive PDF"
                }
            },
            "/convert-upload": {
                "method": "POST",
                "content_type": "multipart/form-data",
                "body": {
                    "video": "Video file (mp4, avi, mov, mkv, webm, flv)",
                    "email": "Email address to receive PDF"
                }
            }
        },
        "features": [
            "YouTube video downloading",
            "Device video upload support",
            "AI-powered speech-to-text (Vosk)",
            "Professional PDF generation",
            "Email delivery",
            "Supported formats: MP4, AVI, MOV, MKV, WEBM, FLV"
        ],
        "powered_by": "Vosk AI + Flask + ReportLab",
        "github": "https://github.com/simrahmad/video-to-pdf-backend"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "success", "message": "Backend is running with Vosk!"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)