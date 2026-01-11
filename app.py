from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi
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
        print(f"Extracting transcript from YouTube: {video_url}")
        
        # Extract video ID
        video_id = extract_video_id(video_url)
        if not video_id:
            return None, "Could not extract video ID from URL"
        
        print(f"Video ID: {video_id}")
        
        # Try to get transcript
        try:
            # Try English first, then auto-generated, then any available
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try to get manual English transcript first
            try:
                transcript = transcript_list.find_manually_created_transcript(['en'])
                transcript_data = transcript.fetch()
                print("Found manual English transcript")
            except:
                # Try auto-generated English
                try:
                    transcript = transcript_list.find_generated_transcript(['en'])
                    transcript_data = transcript.fetch()
                    print("Found auto-generated English transcript")
                except:
                    # Get any available transcript
                    transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
                    transcript_data = transcript.fetch()
                    print("Found available transcript")
            
            # Combine all text from transcript
            full_text = ' '.join([entry['text'] for entry in transcript_data])
            
            print(f"Transcript extracted: {len(full_text)} characters")
            return full_text, None
            
        except Exception as e:
            error_msg = str(e)
            print(f"Transcript error: {error_msg}")
            
            if "Subtitles are disabled" in error_msg or "No transcripts" in error_msg:
                return None, "This video doesn't have captions/subtitles available. Please use the Upload Video feature instead."
            else:
                return None, f"Could not get transcript: {error_msg}"
        
    except Exception as e:
        print(f"Error getting transcript: {str(e)}")
        return None, str(e)

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

def create_pdf_from_text(text, title="Video Transcript"):
    """Create PDF from text"""
    try:
        print("Creating PDF...")
        pdf_file = "output.pdf"
        
        # Clean text
        clean_text = text.replace('\x00', '').strip()
        
        if not clean_text or len(clean_text) < 10:
            clean_text = "Error: Could not extract meaningful text from the content."
        
        # Create PDF with ReportLab
        doc = SimpleDocTemplate(pdf_file, pagesize=letter,
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        story = []
        
        # Add title
        title_para = Paragraph(f"<b>{title}</b>", styles['Title'])
        story.append(title_para)
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
        return pdf_file
        
    except Exception as e:
        print(f"PDF creation error: {str(e)}")
        raise

def send_email(email, pdf_file):
    """Send email with PDF attachment"""
    try:
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
        return True
        
    except Exception as e:
        print(f"Email error: {str(e)}")
        raise

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
        
        # Check if it's a YouTube URL
        is_youtube = "youtube.com" in video_url or "youtu.be" in video_url
        
        if is_youtube:
            # Use YouTube Transcript API
            print("Detected YouTube URL, using Transcript API...")
            text, error = get_youtube_transcript(video_url)
            
            if error:
                return jsonify({
                    "status": "error", 
                    "message": error
                }), 500
            
            if not text:
                return jsonify({
                    "status": "error", 
                    "message": "Could not extract transcript from this video. It may not have captions available. Please use the Upload Video feature instead."
                }), 500
            
            # Create PDF from transcript
            pdf_file = create_pdf_from_text(text, "YouTube Video Transcript")
            
            # Send email
            send_email(email, pdf_file)
            
            # Clean up
            if os.path.exists(pdf_file):
                os.remove(pdf_file)
            
            return jsonify({
                "status": "success", 
                "message": "PDF sent to email successfully! (Used YouTube captions)"
            })
            
        else:
            # For non-YouTube URLs, inform user to use upload
            return jsonify({
                "status": "error", 
                "message": "For non-YouTube videos, please use the Upload Video feature."
            }), 400

    except Exception as e:
        error_msg = str(e)
        print(f"Error: {error_msg}")
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
        
        # Transcribe audio
        print("Transcribing audio to text...")
        text = transcribe_audio(audio_file)
        print(f"Transcription complete! Length: {len(text)} characters")
        
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
        print(f"Error: {str(e)}")
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
        "version": "2.0",
        "status": "running",
        "endpoints": {
            "/": "API information (this page)",
            "/test": "Test endpoint to check if backend is running",
            "/convert": "POST - Convert YouTube video to PDF (using captions)",
            "/convert-upload": "POST - Convert uploaded video file to PDF"
        },
        "usage": {
            "/convert": {
                "method": "POST",
                "content_type": "application/json",
                "body": {
                    "video_url": "YouTube video URL (must have captions)",
                    "email": "Email address to receive PDF"
                },
                "note": "Works only for YouTube videos with captions/subtitles"
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
            "YouTube transcript extraction (FREE - uses official captions)",
            "Device video upload support",
            "AI-powered speech-to-text (Vosk) for uploaded videos",
            "Professional PDF generation",
            "Email delivery",
            "Supported formats: MP4, AVI, MOV, MKV, WEBM, FLV",
            "No API costs or rate limits"
        ],
        "powered_by": "YouTube Transcript API + Vosk AI + Flask + ReportLab",
        "github": "https://github.com/simrahmad/video-to-pdf-backend"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "success", "message": "Backend is running with YouTube Transcript API and Vosk!"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)