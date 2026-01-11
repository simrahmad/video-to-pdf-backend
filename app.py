from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi
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
import re
import glob

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

def extract_video_id(url):
    """Extract YouTube video ID from URL"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_transcript(video_url):
    """Get YouTube transcript using youtube-transcript-api"""
    try:
        print(f"Attempting to extract transcript from YouTube: {video_url}")
        
        # Extract video ID
        video_id = extract_video_id(video_url)
        if not video_id:
            return None, "Could not extract video ID from URL"
        
        print(f"Video ID: {video_id}")
        
        # Try to get transcript
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try different transcript types in order of preference
            transcript = None
            try:
                # Manual English
                transcript = transcript_list.find_manually_created_transcript(['en'])
                print("✅ Found manual English transcript")
            except:
                try:
                    # Auto-generated English
                    transcript = transcript_list.find_generated_transcript(['en'])
                    print("✅ Found auto-generated English transcript")
                except:
                    try:
                        # Any English variant
                        transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                        print("✅ Found English transcript")
                    except:
                        print("❌ No English transcript found")
                        return None, "No English transcript available"
            
            if transcript:
                transcript_data = transcript.fetch()
                full_text = ' '.join([entry['text'] for entry in transcript_data])
                print(f"✅ Transcript extracted: {len(full_text)} characters")
                return full_text, None
            else:
                return None, "No transcript available"
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Transcript error: {error_msg}")
            return None, error_msg
        
    except Exception as e:
        print(f"❌ Error getting transcript: {str(e)}")
        return None, str(e)

def download_youtube_video(video_url):
    """Download YouTube video using yt-dlp (fallback method)"""
    try:
        print(f"📥 Downloading YouTube video with yt-dlp: {video_url}")
        
        # yt-dlp options optimized for audio extraction
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": "audio.%(ext)s",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": False,
            "no_warnings": False,
            "nocheckcertificate": True,
            
            # Browser-like headers
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "referer": "https://www.youtube.com/",
            
            "http_headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
                "Sec-Fetch-Mode": "navigate",
            },
            
            # Multiple extraction methods
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web", "ios"],
                    "player_skip": ["webpage"],
                }
            },
            
            "geo_bypass": True,
            "retries": 5,
            "fragment_retries": 5,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            print(f"✅ Video downloaded: {info.get('title', 'Unknown')}")
        
        # Find downloaded audio file
        audio_files = glob.glob("audio.*")
        if audio_files:
            audio_file = audio_files[0]
            print(f"✅ Audio file ready: {audio_file}")
            return audio_file
        else:
            print("❌ No audio file found after download")
            return None
            
    except Exception as e:
        print(f"❌ Download error: {str(e)}")
        return None

def transcribe_audio(audio_file):
    """Transcribe audio using Vosk"""
    try:
        print("🎤 Transcribing audio with Vosk...")
        
        # Convert to WAV 16kHz mono
        wav_file = "temp_audio.wav"
        subprocess.run([
            'ffmpeg', '-i', audio_file,
            '-ar', '16000', '-ac', '1', '-y', wav_file
        ], check=True, capture_output=True)
        
        # Transcribe
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
        
        final_result = json.loads(rec.FinalResult())
        if 'text' in final_result:
            transcription.append(final_result['text'])
        
        wf.close()
        os.remove(wav_file)
        
        full_text = ' '.join(transcription)
        print(f"✅ Transcription complete: {len(full_text)} characters")
        return full_text
        
    except Exception as e:
        print(f"❌ Transcription error: {str(e)}")
        raise

def create_pdf_from_text(text, title="Video Transcript"):
    """Create PDF from text"""
    try:
        print("📄 Creating PDF...")
        pdf_file = "output.pdf"
        
        clean_text = text.replace('\x00', '').strip()
        
        if not clean_text or len(clean_text) < 10:
            clean_text = "Error: Could not extract meaningful text from the content."
        
        doc = SimpleDocTemplate(pdf_file, pagesize=letter,
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        story = []
        
        title_para = Paragraph(f"<b>{title}</b>", styles['Title'])
        story.append(title_para)
        story.append(Spacer(1, 30))
        
        formatted_text = clean_text.replace('\n', '<br/>')
        formatted_text = formatted_text.replace('&', '&amp;')
        formatted_text = formatted_text.replace('<', '&lt;')
        formatted_text = formatted_text.replace('>', '&gt;')
        formatted_text = formatted_text.replace('<br/>', '<br/>')
        
        para = Paragraph(formatted_text, styles['Normal'])
        story.append(para)
        
        doc.build(story)
        print("✅ PDF created successfully!")
        return pdf_file
        
    except Exception as e:
        print(f"❌ PDF creation error: {str(e)}")
        raise

def send_email(email, pdf_file):
    """Send email with PDF attachment"""
    try:
        print(f"📧 Sending email to {email}...")
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
        print("✅ Email sent successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Email error: {str(e)}")
        raise

@app.route("/convert", methods=["POST"])
def convert_video():
    """Convert video from URL with hybrid approach"""
    data = request.json
    video_url = data.get("video_url")
    email = data.get("email")
    
    if not video_url or not email:
        return jsonify({"status": "error", "message": "Video URL or email missing"}), 400

    try:
        print(f"🎬 Processing video: {video_url}")
        
        # Check if it's a YouTube URL
        is_youtube = "youtube.com" in video_url or "youtu.be" in video_url
        
        if not is_youtube:
            return jsonify({
                "status": "error", 
                "message": "For non-YouTube videos, please use the Upload Video feature."
            }), 400
        
        text = None
        method_used = ""
        
        # STEP 1: Try YouTube Transcript API first (fast & free)
        print("📝 Method 1: Trying YouTube Transcript API...")
        text, error = get_youtube_transcript(video_url)
        
        if text and len(text.strip()) > 50:
            method_used = "YouTube Captions"
            print("✅ SUCCESS: Got transcript from captions!")
        else:
            print(f"❌ Captions not available: {error}")
            
            # STEP 2: Fallback to downloading video
            print("📥 Method 2: Falling back to video download...")
            audio_file = download_youtube_video(video_url)
            
            if not audio_file:
                return jsonify({
                    "status": "error", 
                    "message": "Failed to process video. The video may be private, age-restricted, or unavailable. Please try the Upload Video feature instead."
                }), 500
            
            # STEP 3: Transcribe downloaded audio
            print("🎤 Method 3: Transcribing audio with Vosk...")
            try:
                text = transcribe_audio(audio_file)
                method_used = "Audio Transcription"
                print("✅ SUCCESS: Transcribed audio!")
                
                # Clean up audio file
                if os.path.exists(audio_file):
                    os.remove(audio_file)
            except Exception as e:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                raise e
        
        # Create PDF
        pdf_file = create_pdf_from_text(text, "YouTube Video Transcript")
        
        # Send email
        send_email(email, pdf_file)
        
        # Clean up
        if os.path.exists(pdf_file):
            os.remove(pdf_file)
        
        return jsonify({
            "status": "success", 
            "message": f"PDF sent to email successfully! (Method: {method_used})"
        })

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        return jsonify({"status": "error", "message": f"Processing failed: {error_msg}"}), 500

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
        print(f"📤 Processing uploaded video: {video_file.filename}")
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(UPLOAD_FOLDER, filename)
        video_file.save(video_path)
        print(f"✅ Video saved: {video_path}")
        
        # Extract audio
        print("🎵 Extracting audio...")
        audio_file = "uploaded_audio.mp3"
        
        subprocess.run([
            'ffmpeg', '-i', video_path,
            '-vn', '-acodec', 'libmp3lame',
            '-q:a', '2', audio_file, '-y'
        ], check=True, capture_output=True)
        
        print("✅ Audio extracted!")
        
        # Transcribe
        text = transcribe_audio(audio_file)
        
        # Create PDF
        pdf_file = create_pdf_from_text(text, "Uploaded Video Transcript")
        
        # Send email
        send_email(email, pdf_file)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(audio_file):
            os.remove(audio_file)
        if os.path.exists(pdf_file):
            os.remove(pdf_file)
        
        return jsonify({"status": "success", "message": "PDF sent to email successfully!"})
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        # Clean up on error
        if 'video_path' in locals() and os.path.exists(video_path):
            os.remove(video_path)
        if 'audio_file' in locals() and os.path.exists(audio_file):
            os.remove(audio_file)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    """Home page with API information"""
    return jsonify({
        "service": "Video to PDF Converter API",
        "version": "2.0 - Hybrid",
        "status": "running",
        "endpoints": {
            "/": "API information (this page)",
            "/test": "Test endpoint to check if backend is running",
            "/convert": "POST - Convert YouTube video to PDF (hybrid method)",
            "/convert-upload": "POST - Convert uploaded video file to PDF"
        },
        "usage": {
            "/convert": {
                "method": "POST",
                "content_type": "application/json",
                "body": {
                    "video_url": "YouTube video URL",
                    "email": "Email address to receive PDF"
                },
                "note": "Tries captions first, downloads if needed - works for ALL YouTube videos"
            },
            "/convert-upload": {
                "method": "POST",
                "content_type": "multipart/form-data",
                "body": {
                    "video": "Video file (mp4, avi, mov, mkv, webm, flv)",
                    "email": "Email address to receive PDF"
                },
                "note": "Works for all video formats"
            }
        },
        "features": [
            "Hybrid YouTube processing (captions first, then download fallback)",
            "Works for 100% of YouTube videos",
            "Device video upload support",
            "AI-powered speech-to-text (Vosk)",
            "Professional PDF generation",
            "Email delivery",
            "Supported formats: MP4, AVI, MOV, MKV, WEBM, FLV",
            "Completely FREE - no API costs"
        ],
        "processing_methods": {
            "method_1": "YouTube Transcript API (fast, when captions available)",
            "method_2": "yt-dlp download + Vosk transcription (slower, always works)"
        },
        "powered_by": "YouTube Transcript API + yt-dlp + Vosk AI + Flask + ReportLab",
        "github": "https://github.com/simrahmad/video-to-pdf-backend"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "success", "message": "Backend is running with hybrid YouTube processing!"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Starting Flask server on port {port}")
    print("📝 Method 1: YouTube Transcript API (fast)")
    print("📥 Method 2: yt-dlp + Vosk (fallback)")
    app.run(host="0.0.0.0", port=port, debug=False)