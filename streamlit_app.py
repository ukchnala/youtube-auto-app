import os, re, json, time, asyncio, subprocess, urllib.parse
import requests
import streamlit as st
import edge_tts
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types
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

def get_competitor_data_and_frame(url_or_topic):
    if "http" not in url_or_topic:
        return f"Topic: {url_or_topic}", None
    vid_id = extract_video_id(url_or_topic)
    info_text = ""
    thumb_bytes = None
    
    if vid_id:
        # Download actual visual frame/thumbnail from competitor video to clone exact art style
        for res_type in ["maxresdefault.jpg", "hqdefault.jpg"]:
            try:
                t_url = f"https://img.youtube.com/vi/{vid_id}/{res_type}"
                r = requests.get(t_url, timeout=10)
                if r.status_code == 200 and len(r.content) > 5000:
                    thumb_bytes = r.content
                    break
            except Exception:
                pass
        try:
            t_list = YouTubeTranscriptApi.get_transcript(vid_id, languages=['hi', 'en', 'en-IN'])
            info_text += "Transcript: " + " ".join([t['text'] for t in t_list])[:3500] + "\n"
        except Exception:
            pass
            
    try:
        ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'playlistend': 5}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_or_topic, download=False)
            if 'entries' in info:
                entries = [e for e in info['entries'] if e]
                titles = [e.get('title', '') for e in entries]
                info_text += f"Channel Style & Recent Videos: {', '.join(titles)}\n"
                if not thumb_bytes and entries and entries[0].get('id'):
                    r = requests.get(f"https://img.youtube.com/vi/{entries[0]['id']}/hqdefault.jpg", timeout=10)
                    if r.status_code == 200:
                        thumb_bytes = r.content
            else:
                tags = ", ".join(info.get('tags', [])[:15]) if info.get('tags') else ""
                info_text = f"Title: {info.get('title', '')}\nTags: {tags}\nDesc: {info.get('description', '')[:800]}\n" + info_text
    except Exception:
        pass
    return (info_text if info_text else f"Topic/Video: {url_or_topic}"), thumb_bytes

def free_turbo_ai(prompt, is_json=False):
    for attempt in range(3):
        try:
            url = "https://text.pollinations.ai/"
            payload = {
                "messages": [
                    {"role": "system", "content": "You are an expert Hindi YouTube automation director and visual style cloner. Return exact requested format."},
                    {"role": "user", "content": prompt}
                ],
                "model": "openai",
                "jsonMode": is_json
            }
            r = requests.post(url, json=payload, timeout=70)
            if r.status_code == 200 and r.text:
                return r.text
        except Exception:
            time.sleep(2)
    raise Exception("Network timeout. Kripya dobara button dabayein.")

def smart_ai_call(api_key, prompt, thumb_bytes=None, is_json=False, status_box=None):
    if api_key and len(api_key.strip()) > 10:
        client = genai.Client(api_key=api_key.strip())
        models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.8-flash"]
        for m in models:
            try:
                cfg = {"response_mime_type": "application/json"} if is_json else None
                contents = [prompt]
                if thumb_bytes:
                    contents.append(types.Part.from_bytes(data=thumb_bytes, mime_type="image/jpeg"))
                res = client.models.generate_content(model=m, contents=contents, config=cfg)
                if res and res.text:
                    return res.text
            except Exception:
                continue
    if status_box:
        status_box.info("⚡ Direct Unstoppable AI Engine se Script aur Visual Style Clone ho raha hai...")
    return free_turbo_ai(prompt, is_json=is_json)

def clean_json_parse(raw_text, num_scenes):
    try:
        cleaned = re.sub(r"```json|```", "", raw_text).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            return json.loads(cleaned[start:end+1])
    except Exception:
        pass
    return {
        "visual_style_dna": "hyper-realistic dark cinematic 3D render, volumetric fog, dramatic rim lighting, Unreal Engine 5 style, 8k",
        "script": raw_text,
        "chapters": ["Part 1: Rahasya Ki Shuruwat", "Part 2: Gehra Sach", "Part 3: Anokha Mod", "Part 4: Antim Satya"],
        "prompts": [f"cinematic scene {i+1} matching the story, dramatic lighting, ultra detailed" for i in range(num_scenes)]
    }

def build_cloned_script_and_visuals(comp_data, thumb_bytes, api_key, target_minutes, num_scenes, custom_style, status_box):
    style_hint = f"User requested visual style: {custom_style}" if custom_style else "Analyze the attached competitor image/data and clone its EXACT visual art style (e.g. 3D render, dark realism, anime, historical painting, neon cyber, or documentary photography), color grading, lighting, and mood."
    
    if target_minutes <= 2:
        prompt = f"""
Competitor Video Data:
{comp_data}

{style_hint}

1. Extract the exact "visual_style_dna" (25-word comma-separated style descriptor: art medium, color palette, lighting, camera lens, rendering engine).
2. Write a high-retention viral Hindi voiceover script (180-220 words in Devanagari/Hinglish) on a similar viral angle.
3. Write {num_scenes} scene-by-scene English image prompts where EVERY prompt describes the exact scene action + includes the exact same visual style DNA.

Return ONLY valid JSON:
{{
  "visual_style_dna": "exact style tags...",
  "script": "Full Hindi voiceover script...",
  "prompts": ["Scene 1 description...", "Scene 2 description..."]
}}
"""
        raw = smart_ai_call(api_key, prompt, thumb_bytes=thumb_bytes, is_json=True, status_box=status_box)
        data = clean_json_parse(raw, num_scenes)
        dna = data.get("visual_style_dna", custom_style or "cinematic 3D realistic dark moody lighting, 8k")
        prompts = [f"{p}, {dna}" for p in data.get("prompts", [])]
        while len(prompts) < num_scenes:
            prompts.append(f"Dramatic key moment scene {len(prompts)+1}, {dna}")
        return data.get("script", raw), prompts[:num_scenes], dna

    num_chapters = max(3, min(8, target_minutes // 2))
    status_box.info(f"👁️ Competitor ka Visual Style scan ho raha hai aur {target_minutes} Min ka Plan ban raha hai...")
    
    plan_prompt = f"""
Competitor Video Data:
{comp_data}

{style_hint}

1. Extract the exact "visual_style_dna" (art medium, color grading, lighting, mood, camera style) so all generated visuals look 100% identical in style to this channel.
2. Create a {num_chapters}-chapter outline for a {target_minutes}-minute Hindi video.
3. Generate {num_scenes} detailed scene descriptions matching the story progression.

Return ONLY valid JSON:
{{
  "visual_style_dna": "exact style descriptor...",
  "chapters": ["Chapter 1...", "Chapter 2..."],
  "prompts": ["Scene 1...", "Scene 2..."]
}}
"""
    raw_plan = smart_ai_call(api_key, plan_prompt, thumb_bytes=thumb_bytes, is_json=True, status_box=status_box)
    plan_data = clean_json_parse(raw_plan, num_scenes)
    dna = plan_data.get("visual_style_dna", custom_style or "cinematic realistic documentary style, dramatic lighting, 8k")
    chapters = plan_data.get("chapters", [f"Part {i+1}" for i in range(num_chapters)])
    raw_prompts = plan_data.get("prompts", [])
    prompts = [f"{p}, {dna}" for p in raw_prompts]
    while len(prompts) < num_scenes:
        prompts.append(f"Detailed story scene {len(prompts)+1}, {dna}")

    full_script_parts = []
    for idx, ch in enumerate(chapters):
        status_box.info(f"✍️ AI Script likh raha hai: Chapter {idx+1}/{len(chapters)}...")
        ch_prompt = f"""
Competitor Context: {comp_data[:800]}
Chapter ({idx+1} of {len(chapters)}): {ch}

Write an engaging, high-retention Hindi narration (in Devanagari/Hinglish, 350-400 words) for THIS chapter only. Write ONLY the spoken voiceover words without any titles or stage directions.
"""
        ch_text = smart_ai_call(api_key, ch_prompt, thumb_bytes=None, is_json=False, status_box=status_box)
        full_script_parts.append(ch_text.strip())
        
    return "\n\n".join(full_script_parts), prompts[:num_scenes], dna

def generate_ai_images(prompts, status_box, width, height):
    files = []
    total = len(prompts)
    for i, p in enumerate(prompts):
        status_box.info(f"🎨 Competitor-Style AI Visual {i+1}/{total} ban raha hai...")
        q = urllib.parse.quote(p)
        url = f"https://image.pollinations.ai/prompt/{q}?width={width}&height={height}&seed={500+i}&model=flux&nologo=true"
        fname = f"frame_{i:04d}.jpg"
        ok = False
        for _ in range(3):
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    img = Image.open(fname).convert("RGB").resize((width, height), Image.LANCZOS)
                    img.save(fname, quality=92)
                    files.append(fname)
                    ok = True
                    break
            except Exception:
                time.sleep(1)
        if not ok:
            Image.new("RGB", (width, height), (15, 15, 25)).save(fname)
            files.append(fname)
    return files

async def make_tts(text):
    comm = edge_tts.Communicate(text, FIXED_VOICE, rate="+8%")
    await comm.save("raw_voice.mp3")

def build_audio_and_sfx(num_cuts):
    sound = AudioSegment.from_file("raw_voice.mp3")
    chunks = split_on_silence(sound, min_silence_len=260, silence_thresh=sound.dBFS - 16, keep_silence=75)
    clean = sum(chunks, AudioSegment.empty()) if chunks else sound
    
    boom = Sine(58).to_audio_segment(duration=200).fade_out(160) - 9
    whoosh = WhiteNoise().to_audio_segment(duration=160).low_pass_filter(1250).fade_out(120) - 15
    sfx = boom.overlay(whoosh)
    
    total_ms = len(clean)
    step_ms = max(600, total_ms // max(1, num_cuts))
    for pos in range(step_ms, total_ms - 300, step_ms):
        clean = clean.overlay(sfx, position=pos)
        
    clean.export("final_audio.mp3", format="mp3")
    return "final_audio.mp3", len(clean) / 1000.0

def make_subtitles(audio_path, width, height):
    segments, _ = whisper_model.transcribe(audio_path, word_timestamps=True)
    margin_v = 380 if height > width else 80
    font_sz = 80 if height > width else 64
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_sz},&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,20,20,{margin_v},1

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
    num_loops = max(1, int(total_dur // (len(image_files) * 4)))
    expanded_images = (image_files * num_loops)[:max(len(image_files), int(total_dur // 3.5))]
    clip_dur = max(0.4, total_dur / len(expanded_images))
    
    lines = [f"file '{img}'\nduration {clip_dur:.4f}\n" for img in expanded_images]
    lines.append(f"file '{expanded_images[-1]}'\n")
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

st.title("🔥 Auto-Video App (Visual Style Cloner Edition)")
st.caption("Competitor Visual Frame Scanner | FLUX AI Visuals | Auto Pause-Cut | Viral Captions")

tab1, tab2 = st.tabs(["🤖 Mode 1: Competitor Link -> Clone Style & Video", "📁 Mode 2: Apni Script + Auto/Manual Visuals"])

with tab1:
    comp_url = st.text_input("1. Competitor YouTube Video Link (Jiske Jaise Visuals Chahiye)")
    custom_style = st.text_input("2. Visual Style Lock (Optional - Khali chhodenge toh App khud Video ka Thumbnail/Frame dekh kar style copy karega)", placeholder="e.g. Dark 3D green nature mystery, glowing lighting, Unreal Engine 5")
    
    duration_choice = st.selectbox(
        "3. Video Ki Lambai (Duration) Chunein:",
        [
            "1 Minute (YouTube Shorts / Reels - 9:16 Vertical)",
            "5 Minutes (Long Video - 16:9 Landscape)",
            "10 Minutes (Long Video - 16:9 Landscape)",
            "20 Minutes (Deep Documentary - 16:9 Landscape)",
            "30 Minutes (Mega Documentary - 16:9 Landscape)"
        ]
    )
    
    num_vis = st.slider("4. Kitne Unique AI Visuals Banayein?", 15, 60, 25, 5)
    api_key = st.text_input("5. Gemini API Key (Optional - Khali chhodenge toh bhi 100% Free Turbo Engine se chalega!)", type="password")
    
    if st.button("🚀 CLONE STYLE & GENERATE FULL VIDEO", use_container_width=True):
        if not comp_url:
            st.error("❌ Kripya Competitor YouTube Link daalein!")
        else:
            status = st.empty()
            try:
                target_mins = int(duration_choice.split()[0])
                width, height = (720, 1280) if target_mins == 1 else (1280, 720)
                
                status.info("🕵️ Competitor Video ka Frame aur Visual Style scan ho raha hai...")
                info, thumb_bytes = get_competitor_data_and_frame(comp_url)
                if thumb_bytes:
                    st.image(thumb_bytes, caption="✅ Competitor Frame Scanned for Visual Style Cloning", width=280)
                
                script, prompts, detected_dna = build_cloned_script_and_visuals(info, thumb_bytes, api_key, target_mins, num_vis, custom_style, status)
                st.info(f"🎨 **Cloned Visual Style DNA:** {detected_dna}")
                
                imgs = generate_ai_images(prompts, status, width, height)
                
                status.info("🎙️ Fixed Voiceover + Pause Cut + Boom SFX lag raha hai...")
                asyncio.run(make_tts(script))
                aud, dur = build_audio_and_sfx(len(imgs))
                
                status.info("⚡ Viral Captions aur Final Video Render ho rahi hai...")
                sub = make_subtitles(aud, width, height)
                out = render_ffmpeg(imgs, aud, sub, dur)
                
                status.success(f"✅ Aapki {int(dur//60)} Min {int(dur%60)} Sec ki Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button("📥 Download MP4 Video", f, file_name="cloned_style_video.mp4", mime="video/mp4", use_container_width=True)
            except Exception as e:
                status.error(f"⚠️ Error: {str(e)}")

with tab2:
    user_script = st.text_area("1. Apni Script Paste Karein (Yahan Gemini Pro chat se likhwa kar bhi daal sakte hain)", height=150)
    format_choice = st.radio("2. Video Size Chunein:", ["9:16 Vertical (Shorts)", "16:9 Landscape (Long Video)"], horizontal=True)
    uploaded_files = st.file_uploader("3. Apne 50-60 Visuals Upload Karein", accept_multiple_files=True, type=['jpg', 'jpeg', 'png', 'webp'])
    
    if st.button("⚡ EDIT MY VISUALS NOW", use_container_width=True):
        if not user_script or not uploaded_files:
            st.error("❌ Script aur Photos dono daalein!")
        else:
            status2 = st.empty()
            try:
                w, h = (720, 1280) if "9:16" in format_choice else (1280, 720)
                status2.info("🎙️ Fixed Voiceover + Pause Cut + SFX ban raha hai...")
                asyncio.run(make_tts(user_script))
                aud, dur = build_audio_and_sfx(len(uploaded_files))
                status2.info(f"🖼️ {len(uploaded_files)} Visuals set ho rahe hain...")
                imgs = []
                for i, uf in enumerate(uploaded_files):
                    img = Image.open(uf).convert("RGB").resize((w, h), Image.LANCZOS)
                    p = f"manual_{i:04d}.jpg"
                    img.save(p, quality=90)
                    imgs.append(p)
                status2.info("⚡ Viral Captions + Final Video Render ho rahi hai...")
                sub = make_subtitles(aud, w, h)
                out = render_ffmpeg(imgs, aud, sub, dur)
                status2.success("✅ Aapki Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button("📥 Download Edited Video", f, file_name="edited_video.mp4", mime="video/mp4", use_container_width=True)
            except Exception as e:
                status2.error(f"⚠️ Error: {str(e)}")
                        
