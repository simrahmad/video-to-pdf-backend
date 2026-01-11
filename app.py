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
import re
import time

app = Flask(__name__)

# Load Vosk model
print("Loading Vosk model...")
MODEL_PATH = "model"
if not os.path.exists(MODEL_PATH):
    print("ERROR: Model not found! Please download vosk-model-small-en-us-0.15")
    print("From: https://alphacephei.com/vosk/models")
    exit(1)

model = Model(MODEL_PATH)
print("✅ Vosk model loaded successfully!")

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', '3gp', 'wmv'}

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

def download_via_y2mate(youtube_url):
    """Download YouTube video using Y2Mate as intermediary"""
    try:
        print(f"📥 Using Y2Mate proxy to download: {youtube_url}")
        
        # Extract video ID
        video_id = extract_video_id(youtube_url)
        if not video_id:
            print("❌ Could not extract video ID")
            return None
        
        print(f"📺 Video ID: {video_id}")
        
        # Step 1: Analyze video to get download options
        print("🔍 Step 1: Getting video info from Y2Mate...")
        analyze_url = "https://www.y2mate.com/mates/analyzeV2/ajax"
        
        analyze_data = {
            'k_query': youtube_url,
            'k_page': 'home',
            'hl': 'en',
            'q_auto': '0'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': '*/*',
            'Origin': 'https://www.y2mate.com',
            'Referer': 'https://www.y2mate.com/',
        }
        
        analyze_response = requests.post(
            analyze_url, 
            data=analyze_data, 
            headers=headers,
            timeout=30
        )
        
        if analyze_response.status_code != 200:
            print(f"❌ Y2Mate analyze failed: {analyze_response.status_code}")
            return None
        
        analyze_result = analyze_response.json()
        
        if analyze_result.get('status') != 'ok':
            print(f"❌ Y2Mate returned error: {analyze_result}")
            return None
        
        print("✅ Got video info from Y2Mate")
        
        # Step 2: Get audio download link
        print("🔍 Step 2: Requesting audio conversion...")
        
        # Try to get MP3 audio formats
        links = analyze_result.get('links', {})
        
        # Priority: mp3 > mp4 audio
        k_value = None
        
        # Try MP3 formats first
        if 'mp3' in links:
            mp3_links = links['mp3']
            # Prefer 128kbps (good quality, reasonable size)
            if 'mp3128' in mp3_links:
                k_value = mp3_links['mp3128']['k']
                print("✅ Using MP3 128kbps format")
            elif mp3_links:
                # Get first available MP3
                first_key = list(mp3_links.keys())[0]
                k_value = mp3_links[first_key]['k']
                print(f"✅ Using MP3 format: {first_key}")
        
        # Fallback to MP4 audio
        if not k_value and 'mp4' in links:
            mp4_links = links['mp4']
            if mp4_links:
                # Get lowest quality (audio extraction anyway)
                first_key = list(mp4_links.keys())[0]
                k_value = mp4_links[first_key]['k']
                print(f"✅ Using MP4 format: {first_key}")
        
        if not k_value:
            print("❌ No suitable format found in Y2Mate response")
            return None
        
        # Step 3: Get actual download link
        print("🔗 Step 3: Getting download link...")
        convert_url = "https://www.y2mate.com/mates/convertV2/index"
        
        convert_data = {
            'vid': video_id,
            'k': k_value
        }
        
        convert_response = requests.post(
            convert_url, 
            data=convert_data, 
            headers=headers,
            timeout=30
        )
        
        if convert_response.status_code != 200:
            print(f"❌ Y2Mate convert failed: {convert_response.status_code}")
            return None
        
        convert_result = convert_response.json()
        
        if convert_result.get('status') != 'ok':
            print(f"❌ Y2Mate convert error: {convert_result}")
            return None
        
        download_url = convert_result.get('dlink')
        
        if not download_url:
            print("❌ No download link in Y2Mate response")
            return None
        
        print(f"✅ Got download link!")
        
        # Step 4: Download the audio file
        print("📥 Step 4: Downloading audio from Y2Mate...")
        
        # Add delay to be respectful to Y2Mate servers
        time.sleep(2)
        
        download_response = requests.get(
            download_url, 
            stream=True, 
            timeout=120,
            headers={'User-Agent': headers['User-Agent']}
        )
        
        if download_response.status_code != 200:
            print(f"❌ Download failed: {download_response.status_code}")
            return None
        
        # Save audio file
        audio_file = "audio.mp3"
        total_size = 0
        
        with open(audio_file, 'wb') as f:
            for chunk in download_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
        
        print(f"✅ Downloaded {total_size / (1024*1024):.2f} MB")
        
        # Verify file was created
        if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
            print("❌ Downloaded file is too small or doesn't exist")
            return None
        
        print(f"✅ Audio file ready: {audio_file}")
        return audio_file
        
    except requests.Timeout:
        print("❌ Y2Mate request timed out")
        return None
    except Exception as e:
        print(f"❌ Y2Mate error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def transcribe_audio(audio_file):
    """Transcribe audio using Vosk"""
    try:
        print("🎤 Transcribing audio with Vosk...")
        
        # Convert to WAV 16kHz mono
        wav_file = "temp_audio.wav"
        print("🔄 Converting audio format...")
        
        result = subprocess.run([
            'ffmpeg', '-i', audio_file,
            '-ar', '16000', '-ac', '1', '-y', wav_file
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ FFmpeg error: {result.stderr}")
            raise Exception("Audio conversion failed")
        
        print("✅ Audio converted to WAV")
        
        # Transcribe
        wf = wave.open(wav_file, "rb")
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)
        
        transcription = []
        print("🎙️ Processing audio...")
        
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                if 'text' in result and result['text'].strip():
                    transcription.append(result['text'])
        
        final_result = json.loads(rec.FinalResult())
        if 'text' in final_result and final_result['text'].strip():
            transcription.append(final_result['text'])
        
        wf.close()
        
        # Cleanup WAV file
        if os.path.exists(wav_file):
            os.remove(wav_file)
        
        full_text = ' '.join(transcription)
        print(f"✅ Transcription complete: {len(full_text)} characters")
        
        if len(full_text.strip()) < 10:
            return "No clear speech detected in the video. Please ensure the video contains audible speech."
        
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
            clean_text = "No meaningful text could be extracted from the video."
        
        doc = SimpleDocTemplate(pdf_file, pagesize=letter,
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_para = Paragraph(f"<b>{title}</b>", styles['Title'])
        story.append(title_para)
        story.append(Spacer(1, 30))
        
        # Word count
        word_count = len(clean_text.split())
        info_text = f"<i>Word Count: {word_count} words</i>"
        info_para = Paragraph(info_text, styles['Normal'])
        story.append(info_para)
        story.append(Spacer(1, 20))
        
        # Format text
        formatted_text = clean_text.replace('\n', '<br/>')
        formatted_text = formatted_text.replace('&', '&amp;')
        formatted_text = formatted_text.replace('<', '&lt;')
        formatted_text = formatted_text.replace('>', '&gt;')
        formatted_text = formatted_text.replace('<br/>', '<br/>')
        
        # Add content
        para = Paragraph(formatted_text, styles['Normal'])
        story.append(para)
        
        doc.build(story)
        print("✅ PDF created successfully!")
        return pdf_file
        
    except Exception as e:
        print(f"❌ PDF creation error: {str(e)}")
        raise

def send_email(email, pdf_file, filename="video"):
    """Send email with PDF attachment"""
    try:
        print(f"📧 Sending email to {email}...")
        gmail_user = os.environ.get("GMAIL_USER", "simrahapp@gmail.com")
        gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "abzqxqsrnavbgvta")
        yag = yagmail.SMTP(gmail_user, gmail_password)
        yag.send(
            to=email,
            subject="Your Video Transcript is Ready! 📄",
            contents=f"""Hello!

Your video transcript has been successfully converted to PDF.

Video: {filename}

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
    """Convert video from URL using Y2Mate proxy"""
    data = request.json
    video_url = data.get("video_url")
    email = data.get("email")
    
    if not video_url or not email:
        return jsonify({"status": "error", "message": "Video URL or email missing"}), 400

    audio_file = None
    pdf_file = None
    
    try:
        print(f"🎬 Processing video: {video_url}")
        
        # Check if YouTube URL
        is_youtube = "youtube.com" in video_url or "youtu.be" in video_url
        
        if not is_youtube:
            return jsonify({
                "status": "error",
                "message": "Currently only YouTube URLs are supported. Please use the Upload Video feature for other videos."
            }), 400
        
        # Download using Y2Mate proxy
        print("📥 Downloading via Y2Mate proxy...")
        audio_file = download_via_y2mate(video_url)
        
        if not audio_file:
            return jsonify({
                "status": "error", 
                "message": "Failed to download video. The video may be private, age-restricted, or temporarily unavailable. Please try a different video or use the Upload feature."
            }), 500
        
        # Transcribe audio
        print("🎤 Starting transcription...")
        text = transcribe_audio(audio_file)
        
        # Create PDF
        pdf_file = create_pdf_from_text(text, "YouTube Video Transcript")
        
        # Send email
        send_email(email, pdf_file, video_url)
        
        # Cleanup
        if os.path.exists(audio_file):
            os.remove(audio_file)
        if os.path.exists(pdf_file):
            os.remove(pdf_file)
        
        return jsonify({
            "status": "success", 
            "message": "PDF sent to email successfully! Check your inbox in 1-2 minutes."
        })

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        
        # Cleanup on error
        try:
            if audio_file and os.path.exists(audio_file):
                os.remove(audio_file)
            if pdf_file and os.path.exists(pdf_file):
                os.remove(pdf_file)
        except:
            pass
        
        return jsonify({
            "status": "error", 
            "message": f"Processing failed: {error_msg}"
        }), 500

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
        return jsonify({
            "status": "error", 
            "message": "Invalid file type. Supported: MP4, AVI, MOV, MKV, WEBM, FLV, 3GP, WMV"
        }), 400
    
    video_path = None
    audio_file = None
    pdf_file = None
    
    try:
        print(f"📤 Processing uploaded video: {video_file.filename}")
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(UPLOAD_FOLDER, filename)
        video_file.save(video_path)
        print(f"✅ Video saved: {video_path}")
        
        # Get file size
        file_size = os.path.getsize(video_path) / (1024 * 1024)
        print(f"📊 File size: {file_size:.2f} MB")
        
        # Extract audio
        print("🎵 Extracting audio...")
        audio_file = "uploaded_audio.mp3"
        
        result = subprocess.run([
            'ffmpeg', '-i', video_path,
            '-vn', '-acodec', 'libmp3lame',
            '-q:a', '2', audio_file, '-y'
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ FFmpeg error: {result.stderr}")
            raise Exception("Failed to extract audio from video")
        
        print("✅ Audio extracted!")
        
        # Check if audio file exists
        if not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
            raise Exception("No audio found in the video. Please upload a video with speech.")
        
        # Transcribe
        text = transcribe_audio(audio_file)
        
        # Create PDF
        pdf_file = create_pdf_from_text(text, f"Transcript: {filename}")
        
        # Send email
        send_email(email, pdf_file, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(audio_file):
            os.remove(audio_file)
        if os.path.exists(pdf_file):
            os.remove(pdf_file)
        
        return jsonify({
            "status": "success", 
            "message": "PDF sent to email successfully! Check your inbox in 1-2 minutes."
        })
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        
        # Cleanup on error
        try:
            if video_path and os.path.exists(video_path):
                os.remove(video_path)
            if audio_file and os.path.exists(audio_file):
                os.remove(audio_file)
            if pdf_file and os.path.exists(pdf_file):
                os.remove(pdf_file)
        except:
            pass
        
        return jsonify({
            "status": "error", 
            "message": f"Processing failed: {error_msg}"
        }), 500

@app.route("/", methods=["GET"])
def home():
    """Home page with API information"""
    return jsonify({
        "service": "Video to PDF Converter API",
        "version": "2.0 - Y2Mate Proxy",
        "status": "running",
        "youtube_method": "Y2Mate proxy service",
        "endpoints": {
            "/": "API information (this page)",
            "/test": "Test endpoint to check if backend is running",
            "/convert": "POST - Convert YouTube video URL to PDF (via Y2Mate)",
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
                "note": "Uses Y2Mate proxy to bypass YouTube restrictions"
            },
            "/convert-upload": {
                "method": "POST",
                "content_type": "multipart/form-data",
                "body": {
                    "video": "Video file (mp4, avi, mov, mkv, webm, flv, 3gp, wmv)",
                    "email": "Email address to receive PDF"
                },
                "note": "Direct upload - works for all video formats"
            }
        },
        "features": [
            "YouTube URL support (via Y2Mate proxy)",
            "Device video upload support",
            "AI-powered speech-to-text (Vosk)",
            "Professional PDF generation",
            "Email delivery",
            "Supported formats: MP4, AVI, MOV, MKV, WEBM, FLV, 3GP, WMV",
            "Completely FREE"
        ],
        "limitations": {
            "y2mate_rate_limit": "~50 requests per hour",
            "file_size": "50 MB recommended for uploads",
            "processing_time": "2-5 minutes average"
        },
        "powered_by": "Y2Mate + Vosk AI + Flask + ReportLab",
        "github": "https://github.com/simrahmad/video-to-pdf-backend"
    })

@app.route("/test", methods=["GET"])
def test():
    return jsonify({
        "status": "success", 
        "message": "Backend is running with Y2Mate proxy! YouTube URLs should work now! 🎉"
    })

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print("=" * 60)
    print("🚀 Video to PDF Converter - Y2Mate Proxy Version")
    print("=" * 60)
    print(f"📡 Server starting on port {port}")
    print("✅ Y2Mate proxy enabled for YouTube downloads")
    print("💡 This bypasses YouTube's bot detection!")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False)