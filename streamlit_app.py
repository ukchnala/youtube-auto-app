import os, re, json, time, asyncio, subprocess, urllib.parse
import requests
import streamlit as st
import edge_tts
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from pydub import AudioSegment
from pydub.silence import split_on_silence
from pydub.generators import Sine, WhiteNoise
from faster_whisper import WhisperModel
from PIL import Image

st.set_page_config(page_title="Auto YouTube Studio", page_icon="🔥", layout="centered")

FIXED_VOICE = "hi-IN-MadhurNeural"

@st.cache_resource
def load_whisper():
    return WhisperModel("tiny", device="cpu", compute_type="int8")

whisper_model = load_whisper()

def extract_video_id(url):
    pattern = r"(?:v=|\/shorts\/|\/embed\/|youtu\.be\/)([0-9A-Za-z_-]{11})"
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_competitor_info(url_or_topic):
    if "http" not in url_or_topic:
        return f"Topic: {url_or_topic}"
    vid_id = extract_video_id(url_or_topic)
    info_text = ""
    if vid_id:
        try:
            t_list = YouTubeTranscriptApi.get_transcript(vid_id, languages=['hi', 'en', 'en-IN'])
            info_text += "Transcript: " + " ".join([t['text'] for t in t_list])[:3500] + "\n"
        except Exception:
            pass
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url_or_topic, download=False)
            info_text = f"Title: {info.get('title', '')}\nDesc: {info.get('description', '')[:800]}\n" + info_text
    except Exception:
        pass
    return info_text if info_text else f"Topic: {url_or_topic}"

def ai_brain_plan(comp_data, api_key, num_scenes):
    client = genai.Client(api_key=api_key.strip())
    prompt = f"""
Analyze this competitor video/topic:
{comp_data}

1. Identify the visual style (dark cinematic 3D, mystery, realistic history, neon anime, horror, etc.).
2. Write a high-retention viral Hindi script (in Hinglish/Devanagari) with a crazy 3-second hook.
3. Create {num_scenes} image generation prompts matching that exact visual style.

Return ONLY valid JSON:
{{
  "script": "Full Hindi voiceover script...",
  "prompts": ["Detailed prompt 1", "Detailed prompt 2"]
}}
"""
    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    data = json.loads(res.text)
    return data["script"], data["prompts"]

def generate_ai_images(prompts, status_box):
    files = []
    total = len(prompts)
    for i, p in enumerate(prompts):
        status_box.info(f"🎨 AI Visual {i+1}/{total} generate ho raha hai...")
        q = urllib.parse.quote(f"{p}, cinematic lighting, 8k, vertical 9:16")
        url = f"https://image.pollinations.ai/prompt/{q}?width=720&height=1280&seed={42+i}&nologo=true"
        fname = f"frame_{i:04d}.jpg"
        ok = False
        for _ in range(3):
            try:
                r = requests.get(url, timeout=20)
                if r.status_code == 200:
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    img = Image.open(fname).convert("RGB").resize((720, 1280), Image.LANCZOS)
                    img.save(fname, quality=92)
                    files.append(fname)
                    ok = True
                    break
            except Exception:
                time.sleep(1)
        if not ok:
            Image.new("RGB", (720, 1280), (15, 15, 25)).save(fname)
            files.append(fname)
    return files

async def make_tts(text):
    comm = edge_tts.Communicate(text, FIXED_VOICE, rate="+10%")
    await comm.save("raw_voice.mp3")

def build_audio_and_sfx(num_cuts):
    sound = AudioSegment.from_file("raw_voice.mp3")
    chunks = split_on_silence(sound, min_silence_len=240, silence_thresh=sound.dBFS - 16, keep_silence=65)
    clean = sum(chunks, AudioSegment.empty()) if chunks else sound
    
    boom = Sine(58).to_audio_segment(duration=200).fade_out(160) - 9
    whoosh = WhiteNoise().to_audio_segment(duration=160).low_pass_filter(1250).fade_out(120) - 15
    sfx = boom.overlay(whoosh)
    
    total_ms = len(clean)
    step_ms = max(400, total_ms // max(1, num_cuts))
    for pos in range(step_ms, total_ms - 250, step_ms):
        clean = clean.overlay(sfx, position=pos)
        
    clean.export("final_audio.mp3", format="mp3")
    return "final_audio.mp3", len(clean) / 1000.0

def make_subtitles(audio_path):
    segments, _ = whisper_model.transcribe(audio_path, word_timestamps=True)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,80,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,20,20,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def fmt(s):
        return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}.{int((s-int(s))*100):02d}"
    lines = [header]
    for seg in segments:
        for w in seg.words:
            txt = w.word.strip().upper().replace(",", "").replace(".", "")
            if not txt:
                continue
            lines.append(f"Dialogue: 0,{fmt(w.start)},{fmt(max(w.start+0.12, w.end))},Default,,0,0,0,,{{\\fscx130\\fscy130\\t(0,80,\\fscx100\\fscy100)}}{txt}\n")
    with open("subs.ass", "w", encoding="utf-8") as f:
        f.writelines(lines)
    return "subs.ass"

def render_ffmpeg(image_files, audio_file, sub_file, total_dur):
    clip_dur = max(0.35, total_dur / len(image_files))
    lines = [f"file '{img}'\nduration {clip_dur:.4f}\n" for img in image_files]
    lines.append(f"file '{image_files[-1]}'\n")
    with open("inputs.txt", "w") as f:
        f.writelines(lines)
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "inputs.txt",
        "-i", audio_file,
        "-vf", f"eq=contrast=1.16:saturation=1.25,ass={sub_file}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "final_output.mp4"
    ]
    subprocess.run(cmd, check=True)
    return "final_output.mp4"

st.title("🔥 24/7 Permanent Auto-Video App")
st.caption("Fixed Voiceover | Auto Pause-Cut | AI Visuals | SFX & Viral Captions")

tab1, tab2 = st.tabs(["🤖 Mode 1: Link -> 100% Auto Video", "📁 Mode 2: Script + 50-60 Visuals"])

with tab1:
    api_key = st.text_input("1. Free Gemini API Key", type="password")
    comp_url = st.text_input("2. Competitor YouTube Link (Ya Topic)")
    num_vis = st.slider("3. Kitne AI Visuals Banayein?", 10, 45, 25, 5)
    
    if st.button("🚀 GENERATE FULL VIDEO AUTOMATICALLY", use_container_width=True):
        if not api_key or not comp_url:
            st.error("❌ Kripya API Key aur Competitor Link dono daalein!")
        else:
            status = st.empty()
            try:
                status.info("🕵️ Competitor Video scan ho rahi hai...")
                info = get_competitor_info(comp_url)
                status.info("🧠 Nayi Script aur Visual Prompts ban rahe hain...")
                script, prompts = ai_brain_plan(info, api_key, num_vis)
                imgs = generate_ai_images(prompts, status)
                status.info("🎙️ Fixed Voiceover + Pause Cut + Boom SFX lag raha hai...")
                asyncio.run(make_tts(script))
                aud, dur = build_audio_and_sfx(len(imgs))
                status.info("⚡ Viral Captions aur Final Video Render ho rahi hai...")
                sub = make_subtitles(aud)
                out = render_ffmpeg(imgs, aud, sub, dur)
                status.success("✅ Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button("📥 Download MP4 Video", f, file_name="auto_video.mp4", mime="video/mp4", use_container_width=True)
            except Exception as e:
                status.error(f"⚠️ Error: {str(e)}")

with tab2:
    user_script = st.text_area("1. Apni Script Paste Karein", height=120)
    uploaded_files = st.file_uploader("2. Apne 50-60 Visuals (Photos) Select Karein", accept_multiple_files=True, type=['jpg', 'jpeg', 'png', 'webp'])
    
    if st.button("⚡ EDIT MY VISUALS NOW", use_container_width=True):
        if not user_script or not uploaded_files:
            st.error("❌ Script aur Photos dono daalein!")
        else:
            status2 = st.empty()
            try:
                status2.info("🎙️ Fixed Voiceover + Pause Cut + SFX ban raha hai...")
                asyncio.run(make_tts(user_script))
                aud, dur = build_audio_and_sfx(len(uploaded_files))
                status2.info(f"🖼️ {len(uploaded_files)} Visuals set ho rahe hain...")
                imgs = []
                for i, uf in enumerate(uploaded_files):
                    img = Image.open(uf).convert("RGB").resize((720, 1280), Image.LANCZOS)
                    p = f"manual_{i:04d}.jpg"
                    img.save(p, quality=92)
                    imgs.append(p)
                status2.info("⚡ Viral Captions + Final Video Render ho rahi hai...")
                sub = make_subtitles(aud)
                out = render_ffmpeg(imgs, aud, sub, dur)
                status2.success("✅ Aapki Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button("📥 Download Edited Video", f, file_name="edited_video.mp4", mime="video/mp4", use_container_width=True)
            except Exception as e:
                status2.error(f"⚠️ Error: {str(e)}")
  
