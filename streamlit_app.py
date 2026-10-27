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
from PIL import Image, ImageStat

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

def analyze_frame_style_locally(thumb_bytes):
    try:
        from io import BytesIO
        img = Image.open(BytesIO(thumb_bytes)).convert("RGB")
        stat = ImageStat.Stat(img)
        r, g, b = stat.mean
        brightness = (r + g + b) / 3
        if brightness < 75:
            return "pitch black dark background, extreme macro close-up photography, glowing rim lighting, high contrast mystery documentary style, hyper-realistic 8k, Unreal Engine 5"
        elif g > r and g > b:
            return "cinematic nature documentary photography, deep Moody green tones, volumetric lighting, ultra detailed macro 8k"
        else:
            return "hyper-realistic cinematic 3D documentary render, dramatic studio lighting, sharp focus, 8k resolution"
    except Exception:
        return "pitch black dark background, extreme macro close-up photography, glowing rim lighting, high contrast mystery style, 8k"

def get_competitor_data_and_frame(url_or_topic):
    if "http" not in url_or_topic:
        return {"title": url_or_topic, "text": f"Topic: {url_or_topic}"}, None
    vid_id = extract_video_id(url_or_topic)
    info_text = ""
    title_text = url_or_topic
    thumb_bytes = None
    
    if vid_id:
        for res_type in ["maxresdefault.jpg", "hqdefault.jpg"]:
            try:
                t_url = f"https://img.youtube.com/vi/{vid_id}/{res_type}"
                r = requests.get(t_url, timeout=10)
                if r.status_code == 200 and len(r.content) > 4000:
                    thumb_bytes = r.content
                    break
            except Exception:
                pass
        try:
            t_list = YouTubeTranscriptApi.get_transcript(vid_id, languages=['hi', 'en', 'en-IN'])
            info_text += "Transcript: " + " ".join([t['text'] for t in t_list])[:3000] + "\n"
        except Exception:
            pass
            
    try:
        ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'playlistend': 5}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_or_topic, download=False)
            if 'entries' in info:
                entries = [e for e in info['entries'] if e]
                titles = [e.get('title', '') for e in entries]
                title_text = titles[0] if titles else "Mysterious Nature Facts"
                info_text += f"Channel Style & Recent Videos: {', '.join(titles)}\n"
                if not thumb_bytes and entries and entries[0].get('id'):
                    r = requests.get(f"https://img.youtube.com/vi/{entries[0]['id']}/hqdefault.jpg", timeout=10)
                    if r.status_code == 200:
                        thumb_bytes = r.content
            else:
                title_text = info.get('title', url_or_topic)
                tags = ", ".join(info.get('tags', [])[:12]) if info.get('tags') else ""
                info_text = f"Title: {title_text}\nTags: {tags}\nDesc: {info.get('description', '')[:600]}\n" + info_text
    except Exception:
        pass
    return {"title": title_text, "text": info_text if info_text else f"Topic: {title_text}"}, thumb_bytes

def call_any_ai(api_key, prompt, thumb_bytes=None, is_json=False):
    if api_key and len(api_key.strip()) > 10:
        client = genai.Client(api_key=api_key.strip())
        for m in ["gemini-3.8-flash", "gemini-3.8-pro", "gemini-2.5-flash", "gemini-1.5-flash"]:
            for attempt in range(2):
                try:
                    cfg = {"response_mime_type": "application/json"} if is_json else None
                    contents = [prompt]
                    if thumb_bytes and attempt == 0:
                        contents.append(types.Part.from_bytes(data=thumb_bytes, mime_type="image/jpeg"))
                    res = client.models.generate_content(model=m, contents=contents, config=cfg)
                    if res and res.text:
                        return res.text
                except Exception as e:
                    if "503" in str(e) or "429" in str(e):
                        time.sleep(3)
                        continue
                    break

    try:
        short_p = urllib.parse.quote(prompt[:900])
        r = requests.get(f"https://text.pollinations.ai/{short_p}?model=openai", timeout=25)
        if r.status_code == 200 and len(r.text.strip()) > 20:
            return r.text
    except Exception:
        pass

    for model_name in ["openai", "mistral"]:
        try:
            r = requests.post(
                "https://text.pollinations.ai/",
                json={
                    "messages": [{"role": "user", "content": prompt[:2000]}],
                    "model": model_name,
                    "jsonMode": is_json
                },
                timeout=30
            )
            if r.status_code == 200 and len(r.text.strip()) > 20:
                return r.text
        except Exception:
            pass

    return None

def build_guaranteed_script_and_visuals(comp_info, thumb_bytes, api_key, target_minutes, num_scenes, custom_style, status_box):
    base_dna = custom_style.strip() if custom_style.strip() else analyze_frame_style_locally(thumb_bytes)
    title_subject = comp_info["title"]
    comp_text = comp_info["text"]

    status_box.info("🧠 Competitor ka Visual DNA aur Script taiyar ho rahi hai...")

    prompt = f"""
Based on this video topic/data:
{comp_text[:1200]}

Visual Style DNA: {base_dna}

Write a high-retention viral Hindi documentary narration (in Hinglish/Devanagari) AND {min(num_scenes, 20)} English visual scene descriptions matching the exact Visual Style DNA.

Return ONLY valid JSON:
{{
  "visual_style_dna": "{base_dna}",
  "script": "Detailed Hindi voiceover narration...",
  "scenes": ["Close up of mysterious creature on dark background", "Glowing finger touching tiny spider in pitch black"]
}}
"""
    raw = call_any_ai(api_key, prompt, thumb_bytes=thumb_bytes, is_json=True)
    
    parsed = None
    if raw:
        try:
            cleaned = re.sub(r"```json|```", "", raw).strip()
            s, e = cleaned.find("{"), cleaned.rfind("}")
            if s != -1 and e != -1:
                parsed = json.loads(cleaned[s:e+1])
        except Exception:
            pass

    dna = (parsed.get("visual_style_dna") if parsed else None) or base_dna
    base_script = (parsed.get("script") if parsed else None) or ""
    raw_scenes = (parsed.get("scenes") if parsed else None) or []

    target_parts = 1 if target_minutes <= 2 else max(2, min(6, target_minutes // 2))
    script_parts = [base_script] if len(base_script) > 80 else []

    chapter_angles = [
        "चौंकाने वाली शुरुआत और सबसे बड़ा रहस्य",
        "वैज्ञानिकों की खोज और अनदेखा सच",
        "प्रकृति का सबसे खतरनाक और अजीब नियम",
        "गहराई में छिपा रहस्य जो कोई नहीं जानता",
        "अंतिम सत्य और होश उड़ा देने वाला निष्कर्ष",
        "अनसुलझे सवाल और भविष्य का खतरा"
    ]

    for idx in range(len(script_parts), target_parts):
        status_box.info(f"✍️ Script Part {idx+1}/{target_parts} likha ja raha hai...")
        ch_angle = chapter_angles[idx % len(chapter_angles)]
        ch_prompt = f"Write a 280-word gripping Hindi documentary voiceover narration about '{title_subject}' focusing on '{ch_angle}'. Write ONLY spoken Hindi words in Devanagari/Hinglish without any headings."
        ch_res = call_any_ai(api_key, ch_prompt, thumb_bytes=None, is_json=False)
        if ch_res and len(ch_res.strip()) > 60:
            script_parts.append(re.sub(r"[#*`]", "", ch_res).strip())
        else:
            script_parts.append(
                f"क्या आपने कभी सोचा है कि {title_subject} के पीछे का असली सच क्या है? "
                f"जब आप इसे करीब से देखते हैं, तो पता चलता है कि प्रकृति ने इसके अंदर ऐसे रहस्य छिपा रखे हैं जिन्हें देखकर बड़े-बड़े वैज्ञानिक भी हैरान रह जाते हैं। "
                f"अंधेरे में चमकती हुई ये छोटी सी चीज़ जितनी शांत दिखती है, असलियत में उतनी ही रहस्यमयी और खतरनाक साबित हो सकती है। "
                f"अगर कोई इंसान बिना सोचे-समझे इसे छूने की गलती कर दे, तो जो नतीजा सामने आता है वह किसी के भी रोंगटे खड़े कर सकता है। "
                f"इसके शरीर की बनावट और इसके शिकार करने का तरीका दुनिया के बाकी सभी जीवों से बिल्कुल अलग है। "
                f"यही वजह है कि विशेषज्ञ हमेशा चेतावनी देते हैं कि ऐसी अनोखी चीज़ों को कभी भी हल्के में नहीं लेना चाहिए।"
            )

    full_script = "\n\n".join(script_parts)

    camera_angles = [
        "extreme macro close-up shot",
        "dramatic side profile in pitch black darkness",
        "glowing human fingertip approaching subject in dark",
        "cinematic microscopic detail view",
        "mysterious silhouette with glowing rim light",
        "high-contrast dramatic spotlight angle",
        "ultra-detailed anatomy close-up in darkness",
        "cinematic slow-motion freeze frame look"
    ]
    
    final_prompts = []
    for i in range(num_scenes):
        if i < len(raw_scenes) and isinstance(raw_scenes[i], str):
            scene_desc = raw_scenes[i]
        else:
            angle = camera_angles[i % len(camera_angles)]
            scene_desc = f"{angle} inspired by {title_subject}, intense mysterious atmosphere"
        final_prompts.append(f"{scene_desc}, {dna}")

    return full_script, final_prompts, dna

def generate_ai_images(prompts, status_box, width, height, fallback_thumb=None):
    files = []
    total = len(prompts)
    for i, p in enumerate(prompts):
        status_box.info(f"🎨 Competitor-Style Visual {i+1}/{total} ban raha hai...")
        q = urllib.parse.quote(p[:350])
        url = f"https://image.pollinations.ai/prompt/{q}?width={width}&height={height}&seed={700+i}&model=flux&nologo=true"
        fname = f"frame_{i:04d}.jpg"
        ok = False
        for _ in range(2):
            try:
                r = requests.get(url, timeout=20)
                if r.status_code == 200 and len(r.content) > 2000:
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    img = Image.open(fname).convert("RGB").resize((width, height), Image.LANCZOS)
                    img.save(fname, quality=90)
                    files.append(fname)
                    ok = True
                    break
            except Exception:
                time.sleep(1)
        if not ok:
            if fallback_thumb:
                try:
                    from io import BytesIO
                    base = Image.open(BytesIO(fallback_thumb)).convert("RGB").resize((width, height), Image.LANCZOS)
                    w_crop = int(width * 0.9)
                    h_crop = int(height * 0.9)
                    left = (i * 7) % (width - w_crop)
                    top = (i * 5) % (height - h_crop)
                    cropped = base.crop((left, top, left + w_crop, top + h_crop)).resize((width, height), Image.LANCZOS)
                    cropped.save(fname, quality=90)
                    files.append(fname)
                    continue
                except Exception:
                    pass
            Image.new("RGB", (width, height), (10, 10, 15)).save(fname)
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

st.title("🔥 Auto-Video App (Zero-Error Visual Cloner)")
st.caption("Competitor Frame Scanner | Unstoppable Engine | Auto Pause-Cut | Viral Captions")

tab1, tab2 = st.tabs(["🤖 Mode 1: Competitor Link -> Clone Style & Video", "📁 Mode 2: Apni Script + Auto/Manual Visuals"])

with tab1:
    comp_url = st.text_input("1. Competitor YouTube Video Link (Jiske Jaise Visuals Chahiye)")
    custom_style = st.text_input("2. Visual Style Lock (Optional - Khali chhodenge toh App khud Frame ka Dark/Macro style detect karega)", placeholder="e.g. Pitch black dark background, glowing macro insect, 8k")
    
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
    
    num_vis = st.slider("4. Kitne Unique AI Visuals Banayein? (Fast Render ke liye 20-30 best hai)", 15, 60, 25, 5)
    api_key = st.text_input("5. Gemini API Key (Optional)", type="password")
    
    if st.button("🚀 CLONE STYLE & GENERATE FULL VIDEO", use_container_width=True):
        if not comp_url:
            st.error("❌ Kripya Competitor YouTube Link daalein!")
        else:
            status = st.empty()
            try:
                target_mins = int(duration_choice.split()[0])
                width, height = (720, 1280) if target_mins == 1 else (1280, 720)
                
                status.info("🕵️ Competitor Video ka Frame aur Visual Style scan ho raha hai...")
                comp_info, thumb_bytes = get_competitor_data_and_frame(comp_url)
                if thumb_bytes:
                    st.image(thumb_bytes, caption="✅ Competitor Frame Scanned for Visual Style Cloning", width=280)
                
                script, prompts, detected_dna = build_guaranteed_script_and_visuals(
                    comp_info, thumb_bytes, api_key, target_mins, num_vis, custom_style, status
                )
                st.info(f"🎨 **Cloned Visual Style DNA:** {detected_dna}")
                
                imgs = generate_ai_images(prompts, status, width, height, fallback_thumb=thumb_bytes)
                
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
    user_script = st.text_area("1. Apni Script Paste Karein", height=150)
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
                status2.info(f"🖼️ {len(uploaded_files)} Visuals set ho rahe ہیں...")
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
                    st.download_button("📥 Download Edited Video", f, file_name="ed
