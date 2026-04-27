#!/usr/bin/env python3
"""
Ραδιοφωνικό Δελτίο Ειδήσεων — Ραδιόφωνο Λαντζουνάτο 108 MHz
===============================================================
Δημιουργεί επαγγελματικό ραδιοφωνικό σποτ ειδήσεων 2-3 λεπτών με:

  SECTIONS:
    • Γενικές ειδήσεις  — tanea.gr / documentonews.gr / tovima.gr
    • Αθλητικά          — gazzetta.gr / sdna.gr / sport24.gr
    • Καιρός            — Open-Meteo API (Τριπύλα / Λαντζουνάτο)

  AUDIO:
    • Φωνή              — el-GR-NestorasNeural (Microsoft Neural TTS)
    • Μουσικό χαλί      — background_music.mp3 (βλ. παρακάτω για πηγές)
    • Ducking           — fade in/out στις παύσεις μεταξύ ειδήσεων

Requirements:
    pip install edge-tts feedparser requests beautifulsoup4
    sudo apt install ffmpeg

Μουσικό χαλί (κατέβασε ένα και αποθήκευσέ το ως background_music.mp3):
    • https://pixabay.com/music/main-title-breaking-news-background-music-252187/
    • https://pixabay.com/music/introoutro-news-background-music-144801/
    • https://pixabay.com/music/search/news%20background/

Usage:
    python3 greek_news_mp3.py

Output:
    news.mp3
"""

import asyncio
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import feedparser
import requests
from bs4 import BeautifulSoup

# ── Ρυθμίσεις ─────────────────────────────────────────────────────────────────

NUM_GENERAL  = 12   # Συνολικά νέα (γενικά + αθλητικά μαζί από Google News)
NUM_SPORTS   = 5    # Αθλητικά (από αθλητικά feeds)
OUTPUT_DIR   = "."

#VOICE        = "el-GR-NestorasNeural"
VOICE       = "el-GR-AthinaNeural"
#VOICE_RATE   = "+8%"       # Ραδιοφωνικός ρυθμός
VOICE_RATE   = "-10%"       # Ραδιοφωνικός ρυθμός
VOICE_VOLUME = "+15%"

# Τοποθεσία Λαντζουνάτο / Τριπύλα
WEATHER_LAT  = 37.57
WEATHER_LON  = 21.87
WEATHER_NAME = "Λαντζουνάτο"

MUSIC_FILE   = "background_music.mp3"

# Ένταση μουσικής (dB)
MUSIC_FULL   = -16    # Κανονική ένταση στις παύσεις
#MUSIC_DUCK   = -36    # Χαμηλωμένη κατά την ομιλία
MUSIC_DUCK   = -16    # Χαμηλωμένη κατά την ομιλία

# Διάρκεια fade (δευτερόλεπτα) — πιο αργό = πιο "γλυκό"
FADE_DURATION = 1.8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "el-GR,el;q=0.9",
}

# ── RSS Feeds ──────────────────────────────────────────────────────────────────

GENERAL_FEEDS = [
    # Google News GR — κύρια πηγή (πάντα ενημερωμένη, δεν μπλοκάρει)
    "https://news.google.com/rss?hl=el&gl=GR&ceid=GR:el",
    # Fallback ελληνικά sites
    "https://www.tanea.gr/feed/",
    "https://www.documentonews.gr/feed/",
    "https://www.tovima.gr/feed/",
    "https://www.iefimerida.gr/rss.xml",
]

#SPORTS_FEEDS = [
    # Google News GR — αθλητικά topic (επίσημο sports section)
#    "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JXVnNMV05oTFVOT1RRQUFQAQ?hl=el&gl=GR&ceid=GR:el",
    # Αμιγώς αθλητικά ελληνικά sites
#    "https://www.gazzetta.gr/rss.xml",
#    "https://www.sdna.gr/feed/",
#    "https://www.sport24.gr/rss/",
#    "https://www.onsports.gr/feed/",
#    "https://www.sportal.gr/feed/",
#]

SPORTS_FEEDS = [
    # Google News GR αθλητικά — ΠΡΩΤΟ, με το σωστό /rss/topics/ prefix
    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnNHZ0pIVWlnQVAB?hl=el&gl=GR&ceid=GR:el",
    # Fallback: αμιγώς αθλητικά ελληνικά sites
    "https://www.gazzetta.gr/rss.xml",
    "https://www.sdna.gr/feed/",
    "https://www.sport24.gr/rss/",
    "https://www.onsports.gr/feed/",
]

# ── ffmpeg helpers ─────────────────────────────────────────────────────────────

def run_ffmpeg(args: list[str], verbose: bool = False) -> None:
    level = "info" if verbose else "error"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", level] + args,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg απέτυχε:\n{result.stderr}")


def get_duration_sec(path: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", path
    ], capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def make_silence(path: str, duration_sec: float) -> None:
    """Δημιουργεί αρχείο σιωπής με ffmpeg."""
    if not os.path.exists(path):
        run_ffmpeg([
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo",
            "-t", str(duration_sec),
            "-b:a", "192k",
            path
        ])


# ── Άντληση ειδήσεων ───────────────────────────────────────────────────────────

def fetch_from_feeds(feed_urls: list[str], limit: int, label: str) -> list[str]:
    seen, titles = set(), []
    for url in feed_urls:
        if len(titles) >= limit:
            break
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            before = len(titles)
            for entry in feed.entries:
                title = entry.title.strip()
                # Αφαίρεση "- Πηγή" στο τέλος
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()
                if title and title not in seen and len(title) > 15:
                    seen.add(title)
                    titles.append(title)
                if len(titles) >= limit:
                    break
            added = len(titles) - before
            if added:
                print(f"    ✅ {url.split('/')[2]}: +{added} τίτλοι")
        except Exception as e:
            print(f"    ⚠️  {url.split('/')[2]}: {e}")

    # Scraping fallback αν τα RSS αποτύχουν
    if not titles:
        try:
            resp = requests.get("https://www.tanea.gr/", headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup.find_all(["h2", "h3"]):
                text = tag.get_text(strip=True)
                if len(text) > 20 and text not in seen:
                    seen.add(text)
                    titles.append(text)
                if len(titles) >= limit:
                    break
            print(f"    ✅ Scraping tanea.gr (fallback): {len(titles)} τίτλοι")
        except Exception as e:
            print(f"    ❌ Scraping: {e}")

    return titles[:limit]


# ── Καιρός ────────────────────────────────────────────────────────────────────

def fetch_weather() -> dict | None:
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,"
        f"precipitation_sum,windspeed_10m_max,weathercode"
        f"&timezone=Europe/Athens&forecast_days=1"
    )
    try:
        data = requests.get(url, timeout=10).json()["daily"]
        return {
            "code":  data["weathercode"][0],
            "tmax":  round(data["temperature_2m_max"][0]),
            "tmin":  round(data["temperature_2m_min"][0]),
            "rain":  data["precipitation_sum"][0],
            "wind":  round(data["windspeed_10m_max"][0]),
        }
    except Exception as e:
        print(f"    ⚠️  Καιρός API: {e}")
        return None


def weather_to_greek(w: dict | None) -> str:
    if not w:
        return "Δεν ήταν δυνατή η λήψη πρόγνωσης καιρού σήμερα."

    codes = {
        0: "αίθριος ουρανός", 1: "κυρίως αίθριος", 2: "αραιή συννεφιά",
        3: "συννεφιά", 45: "ομίχλη", 51: "ψιλόβροχο", 53: "ψιλόβροχο",
        61: "ελαφριά βροχή", 63: "μέτρια βροχή", 65: "έντονη βροχή",
        71: "χιονόπτωση", 73: "χιονόπτωση", 75: "έντονη χιονόπτωση",
        80: "ντόπιες βροχές", 81: "μέτριες βροχές", 82: "ισχυρές βροχές",
        95: "καταιγίδες", 99: "ισχυρές καταιγίδες",
    }
    desc = "μεταβλητός καιρός"
    for k in sorted(codes, reverse=True):
        if w["code"] >= k:
            desc = codes[k]
            break

    rain_str = f" Αναμένονται {w['rain']} χιλιοστά βροχής." if w.get("rain", 0) > 0.5 else ""
    wind_str = f" Άνεμοι έως {w['wind']} χιλιόμετρα την ώρα." if w["wind"] > 30 else ""

    return (
        f"Στο {WEATHER_NAME} σήμερα {desc}. "
        f"Θερμοκρασία από {w['tmin']} έως {w['tmax']} βαθμούς Κελσίου."
        f"{rain_str}{wind_str}"
    )


# ── Κατασκευή segments ────────────────────────────────────────────────────────

def greek_date(dt: datetime.date) -> str:
    months = ["Ιανουαρίου","Φεβρουαρίου","Μαρτίου","Απριλίου","Μαΐου","Ιουνίου",
              "Ιουλίου","Αυγούστου","Σεπτεμβρίου","Οκτωβρίου","Νοεμβρίου","Δεκεμβρίου"]
    days   = ["Δευτέρα","Τρίτη","Τετάρτη","Πέμπτη","Παρασκευή","Σάββατο","Κυριακή"]
    return f"{days[dt.weekday()]}, {dt.day} {months[dt.month-1]} {dt.year}"


def time_greeting() -> str:
    """Επιστρέφει χαιρετισμό ανάλογα με την ώρα (ώρα Ελλάδας)."""
    import zoneinfo
    now_hour = datetime.datetime.now(zoneinfo.ZoneInfo("Europe/Athens")).hour
    if 5 <= now_hour < 13:
        return "Καλημέρα."
    elif 13 <= now_hour < 21:
        return "Καλησπέρα."
    else:
        return "Καληνύχτα."


def build_segments(general, sports, weather_text, date_str) -> list[dict]:
    """
    Κάθε segment είναι ένα dict:
      text      → κείμενο για TTS (κενό = μόνο παύση)
      duck      → True: μουσική χαμηλά | False: μουσική κανονικά
      pause_sec → δευτερόλεπτα σιωπής (μόνο αν text=None)
    """
    S = []

    def speech(text, duck=True):
        S.append({"text": text, "duck": duck})

    def pause(sec, duck=False):
        S.append({"pause_sec": sec, "duck": duck})

    greeting = time_greeting()

    # ── Εισαγωγή ──
  #  speech(greeting)
  #  speech(f"Χαίρετε!")
    pause(0.6)
    speech(f"Τα νέα της ημέρας, απο το Λαντζουνάτο 108 FM.")
    pause(0.7)
    speech(f"Σήμερα είναι {date_str} και πάμε να δούμε τι συμβαίνει στην Ελλάδα και στον κόσμο.")
    pause(2.5, duck=False)   # μουσική ανεβαίνει — ακούγεται καλά

    # ── Γενικές ──
    speech("Γενικές ειδήσεις.", duck=True)
    pause(1.2, duck=False)
    for h in general:
        speech(h + ".")
        pause(2.0, duck=False)   # αρκετός χρόνος για fade up/down

    pause(3.0, duck=False)   # μεγάλη παύση μεταξύ sections — μουσική ακούγεται

    # ── Αθλητικά ──
    speech("Αθλητικές ειδήσεις.", duck=True)
    pause(1.2, duck=False)
    for h in sports:
        speech(h + ".")
        pause(2.0, duck=False)

    pause(3.0, duck=False)

    # ── Καιρός ──
    speech("Πρόγνωση καιρού για σήμερα.", duck=True)
    pause(1.2, duck=False)
    speech(weather_text)
    pause(2.5, duck=False)

    # ── Κλείσιμο ──
    speech("Αυτές ήταν οι ειδήσεις από το Λαντζουνάτο 108 FM.")
    pause(4.0, duck=False)   # fade out μουσική — ακούγεται πριν κλείσει

    return S


# ── TTS ───────────────────────────────────────────────────────────────────────

async def _synth_all(segments: list[dict], tmpdir: str) -> None:
    import edge_tts

    async def synth_one(text: str, path: str) -> None:
        comm = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, volume=VOICE_VOLUME)
        await comm.save(path)

    tasks = []
    for i, seg in enumerate(segments):
        if seg.get("text"):
            path = os.path.join(tmpdir, f"seg_{i:03d}.mp3")
            seg["audio_path"] = path
            tasks.append(synth_one(seg["text"], path))

    await asyncio.gather(*tasks)


def synthesize_all(segments: list[dict], tmpdir: str) -> list[dict]:
    print("  🔊 Σύνθεση φωνής (edge-tts, παράλληλα)...")
    asyncio.run(_synth_all(segments, tmpdir))
    return segments


# ── Audio Mixing ──────────────────────────────────────────────────────────────

def db_to_linear(db: float) -> float:
    return round(10 ** (db / 20), 6)


def mix_audio(segments: list[dict], output_path: str, tmpdir: str) -> None:
    print("  🎵 Audio mixing με fade ducking...")

    # ── 1. Χτίζουμε timeline και concat list ──────────────────────────────────
    concat_list  = os.path.join(tmpdir, "concat.txt")
    speech_path  = os.path.join(tmpdir, "speech.mp3")

    # timeline: [(start_sec, end_sec, is_ducked)]
    timeline = []
    cursor   = 0.0

    with open(concat_list, "w", encoding="utf-8") as f:
        for seg in segments:
            if seg.get("audio_path") and os.path.exists(seg["audio_path"]):
                dur = get_duration_sec(seg["audio_path"])
                timeline.append((cursor, cursor + dur, True))   # ομιλία → duck
                cursor += dur
                f.write(f"file '{seg['audio_path']}'\n")
            elif seg.get("pause_sec"):
                dur = seg["pause_sec"]
                ducked = seg.get("duck", False)
                sil_path = os.path.join(tmpdir, f"sil_{dur:.3f}.mp3")
                make_silence(sil_path, dur)
                timeline.append((cursor, cursor + dur, ducked))
                cursor += dur
                f.write(f"file '{sil_path}'\n")

    # Concat φωνή + σιωπές
    run_ffmpeg([
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-b:a", "192k", speech_path
    ])
    total_sec = get_duration_sec(speech_path)
    print(f"    ✅ Ομιλία: {total_sec:.1f}s ({total_sec/60:.1f} λεπτά)")

    # ── 2. Χωρίς μουσική ──────────────────────────────────────────────────────
    if not os.path.exists(MUSIC_FILE):
        print(f"    ⚠️  '{MUSIC_FILE}' δεν βρέθηκε — αποθήκευση χωρίς μουσική.")
        shutil.copy(speech_path, output_path)
        return

    # ── 3. Loop μουσικής ──────────────────────────────────────────────────────
    music_looped = os.path.join(tmpdir, "music_looped.mp3")
    run_ffmpeg([
        "-stream_loop", "-1",
        "-i", MUSIC_FILE,
        "-t", str(total_sec + 3),
        "-b:a", "192k", music_looped
    ])

    # ── 4. Volume envelope με fade in/out ─────────────────────────────────────
    #
    # Λογική:
    #   - Κατά την ομιλία: μουσική στο MUSIC_DUCK
    #   - Στις παύσεις (duck=False): μουσική fade up στο MUSIC_FULL
    #   - Χρησιμοποιούμε ffmpeg volume filter με 'between' expressions
    #   - Fade γίνεται με afade per-segment (πιο απλό και σταθερό)
    #
    # Φτιάχνουμε ένα volume expression που:
    #   • Για κάθε ducked interval → MUSIC_DUCK (linear)
    #   • Για τα υπόλοιπα → MUSIC_FULL (linear)
    #
    # Για το fade χρησιμοποιούμε smooth transition: αντί για hard switch,
    # κάνουμε lerp μεταξύ duck/full στα edge points.

    duck_lin = db_to_linear(MUSIC_DUCK)
    full_lin = db_to_linear(MUSIC_FULL)
    fd       = FADE_DURATION   # fade duration σε δευτερόλεπτα

    # Χτίζουμε expression για το ffmpeg volume filter
    # Για κάθε ducked interval [s, e]:
    #   fade in:  t ∈ [s-fd, s]  → lerp full→duck
    #   ducked:   t ∈ [s, e]     → duck
    #   fade out: t ∈ [e, e+fd]  → lerp duck→full

    # Συλλέγουμε τα ducked intervals
    ducked_intervals = [(s, e) for (s, e, d) in timeline if d]

    if not ducked_intervals:
        # Απλά full volume παντού
        vol_expr = str(full_lin)
    else:
        # Φτιάχνουμε piece-wise expression
        # Για κάθε sample time t, υπολογίζουμε το κατάλληλο volume
        # Χρησιμοποιούμε nested if-then-else
        # ffmpeg volume filter syntax: 'if(cond, val_true, val_false)'

        def make_expr(intervals):
            """Recursive builder για nested if expressions."""
            if not intervals:
                return str(full_lin)
            s, e = intervals[0]
            rest = intervals[1:]

            # Fade in: [s-fd .. s] → full→duck
            fade_in_cond  = f"between(t,{max(0,s-fd):.3f},{s:.3f})"
            fade_in_val   = (
                f"({full_lin}+({duck_lin}-{full_lin})"
                f"*(t-{max(0,s-fd):.3f})/{fd})"
            )
            # Ducked: [s .. e]
            duck_cond = f"between(t,{s:.3f},{e:.3f})"
            duck_val  = str(duck_lin)
            # Fade out: [e .. e+fd] → duck→full
            fade_out_cond = f"between(t,{e:.3f},{min(total_sec,e+fd):.3f})"
            fade_out_val  = (
                f"({duck_lin}+({full_lin}-{duck_lin})"
                f"*(t-{e:.3f})/{fd})"
            )

            inner = make_expr(rest)
            return (
                f"if({fade_in_cond},{fade_in_val},"
                f"if({duck_cond},{duck_val},"
                f"if({fade_out_cond},{fade_out_val},"
                f"{inner})))"
            )

        vol_expr = make_expr(ducked_intervals)

    # Εφαρμογή volume envelope στη μουσική
    music_ducked = os.path.join(tmpdir, "music_ducked.mp3")
    run_ffmpeg([
        "-i", music_looped,
        "-af", f"volume='{vol_expr}':eval=frame",
        "-b:a", "192k",
        music_ducked
    ])

    # ── 5. Τελικό mix: φωνή + ducked μουσική + fade out στο τέλος ───────────
    # Το afade=t=out ξεκινά 3.5 δευτερόλεπτα πριν το τέλος για ομαλό κλείσιμο
    fade_out_start = max(0, total_sec - 3.5)
    run_ffmpeg([
        "-i", speech_path,
        "-i", music_ducked,
        "-filter_complex",
        (
            "[0:a]volume=4dB[v];"
            f"[1:a][v]amix=inputs=2:duration=first:normalize=0[mixed];"
            f"[mixed]afade=t=out:st={fade_out_start:.3f}:d=3.5[out]"
        ),
        "-map", "[out]",
        "-b:a", "192k",
        "-id3v2_version", "3",
        "-metadata", f"title=Ειδήσεις Λαντζουνάτο {datetime.date.today()}",
        "-metadata", "artist=108MHz",
        output_path
    ])

    final_sec = get_duration_sec(output_path)
    print(f"    ✅ Τελική διάρκεια: {final_sec:.0f}s ({final_sec/60:.1f} λεπτά)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today    = datetime.date.today()
    date_str = greek_date(today)
    out_path = os.path.join(OUTPUT_DIR, f"news.mp3")

    print("=" * 58)
    print(f"📻 Ραδιόφωνο Λαντζουνάτο 108MHz — {date_str}")
    print("=" * 58)

    print(f"\n📰 Γενικές ειδήσεις ({NUM_GENERAL})…")
    general = fetch_from_feeds(GENERAL_FEEDS, NUM_GENERAL, "γενικές")
    if not general:
        print("❌ Δεν βρέθηκαν γενικές ειδήσεις.")
        sys.exit(1)
    for i, h in enumerate(general, 1):
        print(f"   {i}. {h[:85]}")

    print(f"\n⚽ Αθλητικές ειδήσεις ({NUM_SPORTS})…")
    sports = fetch_from_feeds(SPORTS_FEEDS, NUM_SPORTS, "αθλητικές")
    if not sports:
        sports = ["Δεν υπάρχουν αθλητικές ειδήσεις αυτή την ώρα."]
    for i, h in enumerate(sports, 1):
        print(f"   {i}. {h[:85]}")

    print(f"\n🌤️  Καιρός {WEATHER_NAME}…")
    weather_text = weather_to_greek(fetch_weather())
    print(f"   {weather_text}")

    segments = build_segments(general, sports, weather_text, date_str)

    print("\n🔊 Σύνθεση φωνής…")
    with tempfile.TemporaryDirectory() as tmpdir:
        segments = synthesize_all(segments, tmpdir)

        print("\n🎚️  Audio mixing…")
        mix_audio(segments, out_path, tmpdir)

    size_kb = os.path.getsize(out_path) // 1024
    print(f"\n✅ Αποθηκεύτηκε: {out_path} ({size_kb} KB)")
    print("=" * 58)


if __name__ == "__main__":
    main()
