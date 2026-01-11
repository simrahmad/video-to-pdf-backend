from flask import Flask, request, jsonify
import requests
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

# RapidAPI Configuration
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "aff5b56eaamsh561b283d1252be3p1b2219jsn1b2c680e7385")
RAPIDAPI_HOST = "youtube-media-downloader.p.rapidapi.com"

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_video_id(url):
    """Extract YouTube video ID from URL"""
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    elif "youtube.com/watch?v=" in url:
        return url.split("v=")[1].split("&")[0]
    return None

def download_youtube_with_rapidapi(video_url):
    """Download YouTube video using RapidAPI"""
    try:
        print(f"Downloading YouTube video via RapidAPI: {video_url}")
        
        # Extract video ID
        video_id = extract_video_id(video_url)
        if not video_id:
            print("Could not extract video ID from URL")
            return None
        
        print(f"Video ID: {video_id}")
        
        # Call RapidAPI to get video info and download links
        api_url = f"https://{RAPIDAPI_HOST}/v2/video/details"
        
        querystring = {"videoId": video_id}
        
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST
        }
        
        print("Calling RapidAPI...")
        response = requests.get(api_url, headers=headers, params=querystring, timeout=30)
        
        if response.status_code != 200:
            print(f"RapidAPI error: {response.status_code}")
            print(f"Response: {response.text}")
            return None
        
        data = response.json()
        print(f"RapidAPI response received")
        
        # Extract audio download URL
        # Try to find audio format
        audio_url = None
        
        # Check if there are downloadable formats
        if "videos" in data and "items" in data["videos"]:
            items = data["videos"]["items"]
            # Look for audio-only format or lowest quality video with audio
            for item in items:
                if "audioOnly" in item and item.get("audioOnly"):
                    audio_url = item.get("url")
                    break
            
            # If no audio-only, get lowest quality video
            if not audio_url and len(items) > 0:
                audio_url = items[-1].get("url")
        
        if not audio_url:
            print("Could not find download URL in RapidAPI response")
            return None
        
        print(f"Found download URL: {audio_url[:50]}...")
        
        # Download the audio/video file
        print("Downloading audio from URL...")
        download_response = requests.get(audio_url, timeout=120, stream=True)
        
        if download_response.status_code == 200:
            audio_file = "audio.mp4"
            with open(audio_file, 'wb') as f:
                for chunk in download_response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Audio downloaded successfully: {audio_file}")
            return audio_file
        else:
            print(f"Failed to download audio: {download_response.status_code}")
            return None
            
    except Exception as e:
        print(f"Error downloading with RapidAPI: {str(e)}")
        return None

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
        
        # Check if it's a YouTube URL
        is_youtube = "youtube.com" in video_url or "youtu.be" in video_url
        
        if is_youtube:
            # Use RapidAPI for YouTube
            print("Detected YouTube URL, using RapidAPI...")
            audio_file = download_youtube_with_rapidapi(video_url)
            
            if not audio_file:
                return jsonify({
                    "status": "error", 
                    "message": "Failed to download YouTube video. The video may be private, age-restricted, or temporarily unavailable. Please try a different public video or use the Upload feature."
                }), 500
        else:
            # For non-YouTube URLs, try direct download
            print("Non-YouTube URL, attempting direct download...")
            try:
                response = requests.get(video_url, timeout=60, stream=True)
                if response.status_code == 200:
                    audio_file = "audio.mp4"
                    with open(audio_file, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    print("Direct download successful!")
                else:
                    return jsonify({
                        "status": "error", 
                        "message": f"Failed to download video. HTTP {response.status_code}"
                    }), 500
            except Exception as e:
                return jsonify({
                    "status": "error", 
                    "message": f"Failed to download video: {str(e)}"
                }), 500

        # Process and send
        success, message = process_video_to_pdf(audio_file, email)
        
        if success:
            return jsonify({"status": "success", "message": message})
        else:
            return jsonify({"status": "error", "message": message}), 500

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
            "/convert": "POST - Convert YouTube video URL to PDF (via RapidAPI)",
            "/convert-upload": "POST - Convert uploaded video file to PDF"
        },
        "usage": {
            "/convert": {
                "method": "POST",
                "content_type": "application/json",
                "body": {
                    "video_url": "YouTube video URL or direct video link",
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
            "YouTube video downloading (via RapidAPI - 100 requests/month free)",
            "Direct video URL support",
            "Device video upload support",
            "AI-powered speech-to-text (Vosk)",
            "Professional PDF generation",
            "Email delivery",
            "Supported formats: MP4, AVI, MOV, MKV, WEBM, FLV"
        ],
        "powered_by": "RapidAPI + Vosk AI + Flask + ReportLab",
        "github": "https://github.com/simrahmad/video-to-pdf-backend"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({"status": "success", "message": "Backend is running with Vosk and RapidAPI!"})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)