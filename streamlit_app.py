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
from PIL import Image, ImageStat, ImageEnhance

st.set_page_config(page_title="Auto YouTube Studio", page_icon="🔥", layout="centered")

VOICE_OPTIONS = {
    "🎙️ Deep Documentary Male (Madhur - Natural)": ("hi-IN-MadhurNeural", "-5Hz", "+1%"),
    "🎙️ Crisp Storytelling Female (Swara - Natural)": ("hi-IN-SwaraNeural", "-2Hz", "+2%")
}

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
        if brightness < 80:
            return "pitch black dark background, extreme macro close-up photography, glowing rim lighting, high contrast mystery documentary style, hyper-realistic 8k, Unreal Engine 5, no text"
        elif g > r and g > b:
            return "cinematic nature documentary photography, deep moody green tones, volumetric lighting, ultra detailed macro 8k, no text"
        else:
            return "hyper-realistic cinematic 3D documentary render, dramatic studio lighting, sharp focus, 8k resolution, no text"
    except Exception:
        return "pitch black dark background, extreme macro close-up photography, glowing rim lighting, high contrast mystery style, 8k, no text"

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
                title_text = titles[0] if titles else "Mysterious Nature Documentary"
                info_text += f"Channel Style & Recent Videos: {', '.join(titles)}\n"
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
                        time.sleep(2)
                        continue
                    break

    headers = {"User-Agent": "Mozilla/5.0"}
    for model_name in ["openai", "mistral"]:
        try:
            r = requests.post(
                "https://text.pollinations.ai/",
                json={
                    "messages": [{"role": "user", "content": prompt[:2200]}],
                    "model": model_name,
                    "jsonMode": is_json
                },
                headers=headers,
                timeout=30
            )
            if r.status_code == 200 and len(r.text.strip()) > 20:
                return r.text
        except Exception:
            pass
    return None

DEV_TO_ROMAN = {
    'अ':'A','आ':'AA','इ':'I','ई':'EE','उ':'U','ऊ':'OO','ऋ':'RI','ए':'E','ऐ':'AI','ओ':'O','औ':'AU',
    'क':'KA','ख':'KHA','ग':'GA','घ':'GHA','च':'CHA','छ':'CHHA','ज':'JA','झ':'JHA','ट':'TA','ठ':'THA',
    'ड':'DA','ढ':'DHA','ण':'NA','त':'TA','थ':'THA','द':'DA','ध':'DHA','न':'NA','प':'PA','फ':'PHA',
    'ब':'BA','भ':'BHA','म':'MA','य':'YA','र':'RA','ल':'LA','व':'VA','श':'SHA','ष':'SHA','स':'SA','ह':'HA',
    'ा':'A','ि':'I','ी':'EE','ु':'U','ू':'OO','े':'E','ै':'AI','ो':'O','ौ':'AU','ं':'N','ँ':'N','्':'',
    '़':'','।':'','?':'','!':'',',':'','.':''
}

def to_clean_roman(text):
    ascii_only = re.sub(r'[^A-Za-z0-9\s]', '', text)
    if len(ascii_only.strip()) > len(text) * 0.45:
        return ascii_only.upper()
    out = []
    for ch in text:
        if ch in DEV_TO_ROMAN:
            out.append(DEV_TO_ROMAN[ch])
        elif ch.isascii() and (ch.isalnum() or ch == ' '):
            out.append(ch.upper())
    return re.sub(r'\s+', ' ', "".join(out)).strip()

def build_guaranteed_script_and_visuals(comp_info, thumb_bytes, api_key, target_minutes, num_scenes, custom_style, status_box):
    base_dna = custom_style.strip() if custom_style.strip() else analyze_frame_style_locally(thumb_bytes)
    title_subject = comp_info["title"]
    comp_text = comp_info["text"]

    status_box.info("🧠 Competitor ka Visual DNA aur Natural Documentary Script ban rahi hai...")

    prompt = f"""
Topic/Competitor Data:
{comp_text[:1400]}

Target Visual Style DNA: {base_dna}

1. Write a dramatic, natural-sounding Hindi documentary narration (in Devanagari Hindi, using natural pauses with commas and full stops so voiceover sounds like a real human storyteller).
2. Also provide 'hinglish_captions': the EXACT same script written in Roman Hinglish (English alphabet, e.g. 'KYA AAPNE KABHI SOCHA HAI...') for on-screen subtitles.
3. Create {num_scenes} COMPLETELY DIFFERENT, specific English visual scene descriptions showing different angles, actions, anatomy, environments, and moments of the story.

Return ONLY valid JSON:
{{
  "visual_style_dna": "{base_dna}",
  "script": "Full Hindi narration in Devanagari...",
  "hinglish_captions": "Full narration in Roman Hinglish...",
  "scenes": [
    "Extreme macro close-up of glowing spider eyes in pitch black darkness",
    "Microscopic view of venomous fangs dripping glowing liquid in dark",
    "Human finger slowly approaching a tiny creature on a dark leaf"
  ]
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
    hinglish_sub = (parsed.get("hinglish_captions") if parsed else None) or ""
    raw_scenes = (parsed.get("scenes") if parsed else None) or []

    target_parts = 1 if target_minutes <= 2 else max(2, min(6, target_minutes // 2))
    script_parts = [base_script] if len(base_script) > 80 else []

    chapter_angles = [
        "चौंकाने वाली शुरुआत और सबसे बड़ा रहस्य",
        "वैज्ञानिकों की खोज और अनदेखा सच",
        "प्रकृति का सबसे खतरनाक और अजीब नियम",
        "अंतिम सत्य और होश उड़ा देने वाला निष्कर्ष"
    ]

    for idx in range(len(script_parts), target_parts):
        status_box.info(f"✍️ Documentary Script Part {idx+1}/{target_parts} likha ja raha hai...")
        ch_angle = chapter_angles[idx % len(chapter_angles)]
        ch_prompt = f"Write a 250-word dramatic, human-like Hindi documentary narration about '{title_subject}' ({ch_angle}). Use short punchy sentences with commas for natural breathing pauses. Write ONLY spoken Hindi words in Devanagari."
        ch_res = call_any_ai(api_key, ch_prompt, thumb_bytes=None, is_json=False)
        if ch_res and len(ch_res.strip()) > 60:
            script_parts.append(re.sub(r"[#*`]", "", ch_res).strip())
        else:
            script_parts.append(
                f"जरा सोचिए, जिस चीज़ को हम मामूली समझ कर नज़रअंदाज़ कर देते हैं, उसके पीछे कितना बड़ा रहस्य छिपा हो सकता है। "
                f"जब वैज्ञानिकों ने इसे माइक्रोस्कोप के नीचे रखकर देखा, तो उनके भी होश उड़ गए। "
                f"अंधेरे में दिखने वाला यह नज़ारा जितना अजीब है, असलियत में उतना ही खतरनाक भी है। "
                f"एक छोटी सी गलती, और सेकंड के सौवें हिस्से में सब कुछ बदल सकता है।"
            )

    full_script = "\n\n".join(script_parts)
    if not hinglish_sub or len(hinglish_sub) < 40:
        hinglish_sub = to_clean_roman(full_script)

    unique_scene_templates = [
        f"extreme macro close-up of {title_subject} glowing eyes and intricate body texture in pitch darkness",
        f"human fingertip cautiously approaching a tiny mysterious creature in pitch black void, rim lighting",
        f"microscopic anatomy view of glowing biological fibers and venom glands in dark",
        f"dramatic side silhouette of tiny creature standing on a sharp edge in pitch black background",
        f"high-speed freeze frame of tiny predator striking in complete darkness, glowing particles",
        f"3D X-ray cross-section showing internal glowing organs against pitch black background",
        f"cinematic overhead shot of a tiny mysterious specimen under a single dramatic spotlight",
        f"extreme close-up of microscopic claws gripping a glowing surface in pitch dark",
        f"mysterious bioluminescent droplets falling in slow motion against black background",
        f"scale comparison shot showing tiny creature next to a glowing needle tip in darkness",
        f"dramatic low-angle hero shot of mysterious organism looking giant and terrifying in dark",
        f"glowing neural network pathways inside a tiny creature brain, dark documentary 3D render"
    ]
    
    final_prompts = []
    for i in range(num_scenes):
        if i < len(raw_scenes) and isinstance(raw_scenes[i], str) and len(raw_scenes[i]) > 12:
            scene_desc = re.sub(r"^Scene\s*\d+\s*:\s*", "", raw_scenes[i])
        else:
            scene_desc = unique_scene_templates[i % len(unique_scene_templates)]
        final_prompts.append(f"{scene_desc}, {dna}, no text, no watermark")

    return full_script, hinglish_sub, final_prompts, dna

def generate_unique_ai_images(prompts, status_box, width, height):
    files = []
    total = len(prompts)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0"}
    models_to_try = ["flux", "turbo", ""]
    
    for i, p in enumerate(prompts):
        status_box.info(f"🎨 Unique AI Visual {i+1}/{total} ban raha hai (100% Naya Scene)...")
        clean_p = urllib.parse.quote(p[:300])
        fname = f"frame_{i:04d}.jpg"
        ok = False
        
        for attempt, m_name in enumerate(models_to_try):
            try:
                seed_val = 2000 + (i * 173) + attempt
                m_param = f"&model={m_name}" if m_name else ""
                url = f"https://image.pollinations.ai/prompt/{clean_p}?width={width}&height={height}&seed={seed_val}&nologo=true{m_param}"
                r = requests.get(url, headers=headers, timeout=30)
                if r.status_code == 200 and len(r.content) > 3000:
                    with open(fname, "wb") as f:
                        f.write(r.content)
                    img = Image.open(fname).convert("RGB").resize((width, height), Image.LANCZOS)
                    img = ImageEnhance.Contrast(img).enhance(1.12)
                    img.save(fname, quality=92)
                    files.append(fname)
                    ok = True
                    break
            except Exception:
                time.sleep(1.5)
                
        if not ok:
            try:
                short_q = urllib.parse.quote(f"extreme macro close up mysterious dark creature scene {i+1}, pitch black background, glowing rim light, 8k, no text")
                url2 = f"https://image.pollinations.ai/prompt/{short_q}?width={width}&height={height}&seed={9500+i}&nologo=true"
                r2 = requests.get(url2, headers=headers, timeout=25)
                if r2.status_code == 200 and len(r2.content) > 2000:
                    with open(fname, "wb") as f:
                        f.write(r2.content)
                    img = Image.open(fname).convert("RGB").resize((width, height), Image.LANCZOS)
                    img.save(fname, quality=92)
                    files.append(fname)
                    ok = True
            except Exception:
                pass
                
        if not ok:
            # Never repeat competitor thumbnail!
            Image.new("RGB", (width, height), (12, 12, 18)).save(fname)
            files.append(fname)
            
    return files

async def make_tts(text, voice_id, pitch_val, rate_val):
    comm = edge_tts.Communicate(text, voice_id, pitch=pitch_val, rate=rate_val)
    await comm.save("raw_voice.mp3")

def build_natural_audio_and_sfx(num_cuts):
    sound = AudioSegment.from_file("raw_voice.mp3")
    chunks = split_on_silence(sound, min_silence_len=450, silence_thresh=sound.dBFS - 18, keep_silence=210)
    clean = sum(chunks, AudioSegment.empty()) if chunks else sound
    
    sub_bass = Sine(48).to_audio_segment(duration=280).fade_in(30).fade_out(220) - 14
    whoosh = WhiteNoise().to_audio_segment(duration=180).low_pass_filter(900).fade_out(140) - 20
    sfx = sub_bass.overlay(whoosh)
    
    total_ms = len(clean)
    step_ms = max(2800, total_ms // max(1, min(num_cuts, 25)))
    for pos in range(step_ms, total_ms - 500, step_ms):
        clean = clean.overlay(sfx, position=pos)
        
    clean.export("final_audio.mp3", format="mp3")
    return "final_audio.mp3", len(clean) / 1000.0

def make_subtitles_direct(hinglish_text, total_dur, width, height):
    margin_v = 200 if height > width else 60
    font_sz = 64 if height > width else 50
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_sz},&H0000FFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,4,2,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def fmt(s):
        return f"{int(s//3600)}:{int((s%3600)//60):02d}:{int(s%60):02d}.{int((s-int(s))*100):02d}"
    
    clean_roman = to_clean_roman(hinglish_text)
    words = [w.strip() for w in clean_roman.split() if w.strip()]
    if not words:
        words = ["WATCH", "FULL", "VIDEO"]
        
    chunks = [" ".join(words[i:i+3]) for i in range(0, len(words), 3)]
    step = max(0.45, total_dur / max(1, len(chunks)))
    
    lines = [header]
    curr_t = 0.0
    for ch in chunks:
        end_t = min(total_dur, curr_t + step)
        lines.append(
            f"Dialogue: 0,{fmt(curr_t)},{fmt(end_t)},Default,,0,0,0,,{{\\fscx115\\fscy115\\t(0,90,\\fscx100\\fscy100)}}{ch}\n"
        )
        curr_t = end_t
        if curr_t >= total_dur:
            break
            
    with open("subs.ass", "w", encoding="utf-8") as f:
        f.writelines(lines)
    return "subs.ass"

def create_motion_frames(image_files, total_dur, width, height, status_box):
    status_box.info("🎬 Visuals mein Smooth Zoom-In aur Documentary Motion lag raha hai...")
    motion_entries = []
    num_base = len(image_files)
    scene_dur = max(2.2, total_dur / max(1, num_base))
    steps_per_scene = 6
    step_dur = scene_dur / steps_per_scene
    
    idx_counter = 0
    cur_t = 0.0
    while cur_t < total_dur:
        for i, img_path in enumerate(image_files):
            if cur_t >= total_dur:
                break
            try:
                base = Image.open(img_path).convert("RGB").resize((width, height), Image.LANCZOS)
                zoom_in = (i % 2 == 0)
                for s in range(steps_per_scene):
                    factor = (s / steps_per_scene) * 0.12
                    if not zoom_in:
                        factor = 0.12 - factor
                    cw = int(width * (1.0 - factor))
                    ch = int(height * (1.0 - factor))
                    left = (width - cw) // 2
                    top = (height - ch) // 2
                    frame = base.crop((left, top, left + cw, top + ch)).resize((width, height), Image.LANCZOS)
                    m_name = f"m_{idx_counter:05d}.jpg"
                    frame.save(m_name, quality=88)
                    motion_entries.append((m_name, step_dur))
                    idx_counter += 1
                    cur_t += step_dur
            except Exception:
                motion_entries.append((img_path, scene_dur))
                cur_t += scene_dur
    return motion_entries

def render_ffmpeg(image_files, audio_file, sub_file, total_dur, width, height, status_box):
    motion_list = create_motion_frames(image_files, total_dur, width, height, status_box)
    status_box.info("⚡ Final HD Video aur Captions Render ho rahe hain...")
    lines = [f"file '{fname}'\nduration {dur:.4f}\n" for fname, dur in motion_list]
    lines.append(f"file '{motion_list[-1][0]}'\n")
    with open("inputs.txt", "w") as f:
        f.writelines(lines)
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "inputs.txt",
        "-i", audio_file,
        "-vf", f"eq=contrast=1.12:saturation=1.18,ass={sub_file}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "final_output.mp4"
    ]
    subprocess.run(cmd, check=True)
    return "final_output.mp4"

st.title("🔥 Pro Documentary Auto-Video Studio")
st.caption("100% Unique AI Visuals | Deep Human-Like Voice | Smooth Zoom Motion | Fixed Hinglish Captions")

tab1, tab2 = st.tabs(["🤖 Mode 1: Competitor Link -> Pro Video", "📁 Mode 2: Apni Script + Visuals"])

with tab1:
    comp_url = st.text_input("1. Competitor YouTube Video Link (Ya Topic)")
    custom_style = st.text_input("2. Visual Style Lock (Optional)", placeholder="e.g. Pitch black dark background, glowing macro insect, 8k")
    voice_choice = st.selectbox("3. Voiceover Tone Chunein:", list(VOICE_OPTIONS.keys()))
    
    duration_choice = st.selectbox(
        "4. Video Ki Lambai (Duration) Chunein:",
       "1 Minute (YouTube Shorts / Reels - 9:16 Vertical)",
            "5 Minutes (Long Video - 16:9 Landscape)",
            "10 Minutes (Long Video - 16:9 Landscape)",
            "20 Minutes (Deep Documentary - 16:9 Landscape)",
            "30 Minutes (Mega Documentary - 16:9 Landscape)"
        ]
    )
    
    num_vis = st.slider("5. Kitne Unique AI Visuals Banayein?", 12, 45, 20, 4)
    api_key = st.text_input("6. Gemini API Key (Optional)", type="password")
    
    if st.button("🚀 GENERATE PRO DOCUMENTARY VIDEO", use_container_width=True):
        if not comp_url:
            st.error("❌ Kripya Competitor YouTube Link daalein!")
        else:
            status = st.empty()
            try:
                target_mins = int(duration_choice.split()[0])
                width, height = (720, 1280) if target_mins == 1 else (1280, 720)
                v_id, v_pitch, v_rate = VOICE_OPTIONS[voice_choice]
                
                status.info("🕵️ Competitor Video ka Visual Style scan ho raha hai...")
                comp_info, thumb_bytes = get_competitor_data_and_frame(comp_url)
                
                script, hinglish_sub, prompts, detected_dna = build_guaranteed_script_and_visuals(
                    comp_info, thumb_bytes, api_key, target_mins, num_vis, custom_style, status
                )
                st.info(f"🎨 **Cloned Visual Style DNA:** {detected_dna}")
                
                imgs = generate_unique_ai_images(prompts, status, width, height)
                
                st.write("✅ **Generated Unique AI Visuals Preview (No Thumbnail Used!):**")
                cols = st.columns(4)
                for idx_preview in range(min(4, len(imgs))):
                    cols[idx_preview].image(imgs[idx_preview], caption=f"Scene {idx_preview+1}")
                
                status.info("🎙️ Deep Documentary Voiceover + Natural Pauses + Bass SFX ban raha hai...")
                asyncio.run(make_tts(script, v_id, v_pitch, v_rate))
                aud, dur = build_natural_audio_and_sfx(len(imgs))
                
                sub = make_subtitles_direct(hinglish_sub, dur, width, height)
                out = render_ffmpeg(imgs, aud, sub, dur, width, height, status)
                
                status.success(f"✅ Aapki {int(dur//60)} Min {int(dur%60)} Sec ki Pro Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button(
                        "📥 Download Pro MP4 Video",
                        f,
                        file_name="pro_documentary_video.mp4",
                        mime="video/mp4",
                        use_container_width=True
                    )
            except Exception as e:
                status.error(f"⚠️ Error: {str(e)}")

with tab2:
    user_script = st.text_area("1. Apni Script Paste Karein", height=150)
    voice_choice2 = st.selectbox("2. Voiceover Tone:", list(VOICE_OPTIONS.keys()), key="v2")
    format_choice = st.radio("3. Video Size Chunein:", ["9:16 Vertical (Shorts)", "16:9 Landscape (Long Video)"], horizontal=True)
    uploaded_files = st.file_uploader("4. Apne Visuals Upload Karein", accept_multiple_files=True, type=['jpg', 'jpeg', 'png', 'webp'])
    
    if st.button("⚡ EDIT MY VISUALS NOW", use_container_width=True):
        if not user_script or not uploaded_files:
            st.error("❌ Script aur Photos dono daalein!")
        else:
            status2 = st.empty()
            try:
                w, h = (720, 1280) if "9:16" in format_choice else (1280, 720)
                v_id, v_pitch, v_rate = VOICE_OPTIONS[voice_choice2]
                status2.info("🎙️ Deep Voiceover + Natural Pauses + SFX ban raha hai...")
                asyncio.run(make_tts(user_script, v_id, v_pitch, v_rate))
                aud, dur = build_natural_audio_and_sfx(len(uploaded_files))
                status2.info(f"🖼️ {len(uploaded_files)} Visuals set ho rahe hain...")
                imgs = []
                for i, uf in enumerate(uploaded_files):
                    img = Image.open(uf).convert("RGB").resize((w, h), Image.LANCZOS)
                    p = f"manual_{i:04d}.jpg"
                    img.save(p, quality=90)
                    imgs.append(p)
                sub = make_subtitles_direct(user_script, dur, w, h)
                out = render_ffmpeg(imgs, aud, sub, dur, w, h, status2)
                status2.success("✅ Aapki Video Ready Hai!")
                st.video(out)
                with open(out, "rb") as f:
                    st.download_button(
                        "📥 Download Edited Video",
                        f,
                        file_name="edited_video.mp4",
                        mime="video/mp4",
                        use_container_width=True
                    )
            except Exception as e:
                status2.error(f"⚠️ Error: {str(e)}")
