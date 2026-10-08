import sys
import time
import re
from pathlib import Path
from statistics import median

import av
import numpy as np
from faster_whisper import WhisperModel


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_SIZE = "base"

SAMPLE_RATE = 16000
CHUNK_SECONDS = 5

CONFIDENCE_THRESHOLD = 0.70
NUDGE_COOLDOWN_SECONDS = 10

AUDIO_PATH = (
    Path(__file__).resolve().parent.parent
    / "audio"
    / "recordings"
    / "q4_demo_objection.wav"
)


# ============================================================
# SIGNAL DEFINITIONS
# ============================================================

SIGNALS = {
    "PRICE_OBJECTION": {
        "keywords": [
            "too expensive",
            "very expensive",
            "premium is expensive",
            "premium too high",
            "cost too much",
            "can't afford",
            "cannot afford",
            "too costly",
            "expensive",
        ],
        "confidence": 0.92,
        "priority": "HIGH",
        "nudge": (
            "Acknowledge the premium concern and offer to explain "
            "available payment options or servicing support."
        ),
    },

    "FRUSTRATION": {
        "keywords": [
            "frustrated",
            "frustrating",
            "frustration",
            "angry",
            "annoyed",
            "ridiculous",
            "terrible",
            "not happy",
            "fed up",
            "this is useless",
            "waste of time",
            "nobody is helping",
            "no one is helping",
            "already explained",
            "explained this twice",
        ],
        "confidence": 0.88,
        "priority": "HIGH",
        "nudge": (
            "Acknowledge the customer's frustration, slow down, "
            "and address the immediate concern before continuing."
        ),
    },

    "PAYMENT_DIFFICULTY": {
        "keywords": [
            "can't pay",
            "cannot pay",
            "difficult to pay",
            "difficulty paying",
            "payment problem",
            "payment issue",
            "unable to pay",
            "how can i pay",
            "payment options",
        ],
        "confidence": 0.84,
        "priority": "HIGH",
        "nudge": (
            "Offer to explain the available premium payment channels "
            "or arrange servicing support."
        ),
    },

    "RENEWAL_INTENT": {
        "keywords": [
            "i want to renew",
            "want to renew",
            "renew my policy",
            "continue my policy",
            "i'll renew",
            "i will renew",
            "yes i want to continue",
        ],
        "confidence": 0.90,
        "priority": "MEDIUM",
        "nudge": (
            "Customer is showing renewal intent. Move toward confirming "
            "the next renewal/payment step."
        ),
    },

    "HUMAN_SUPPORT": {
        "keywords": [
            "speak to someone",
            "speak to a person",
            "talk to someone",
            "human agent",
            "customer service",
            "call me back",
            "callback",
            "i want a human",
            "i need a human",
            "let me speak to someone",
        ],
    },

    "CROSS_SELL_OPPORTUNITY": {
        "keywords": [
            "another vehicle",
            "second vehicle",
            "another car",
            "second car",
            "additional vehicle",
            "multiple vehicles",
        ],
        "confidence": 0.86,
        "priority": "MEDIUM",
        "nudge": (
            "Potential cross-sell opportunity detected. "
            "If appropriate, ask whether the customer needs "
            "coverage for the additional vehicle."
        ),
    },

    "COMPLIANCE_RISK": {
        "keywords": [
            "guaranteed",
            "definitely covered",
            "you will get",
            "no risk",
            "guaranteed return",
            "guaranteed benefit",
        ],
        "confidence": 0.93,
        "priority": "HIGH",
        "nudge": (
            "Compliance check: avoid unsupported guarantees or definitive "
            "coverage/benefit claims. Verify the policy terms."
        ),
    },
}


# ============================================================
# AUDIO LOADING
# ============================================================

def load_audio(path):
    container = av.open(str(path))

    stream = container.streams.audio[0]

    original_sample_rate = stream.rate

    samples = []

    for frame in container.decode(audio=0):
        array = frame.to_ndarray()

        # Convert stereo/multi-channel to mono
        if array.ndim > 1:
            array = np.mean(array, axis=0)

        samples.append(array.astype(np.float32))

    container.close()

    audio = np.concatenate(samples)

    # Normalize
    max_value = np.max(np.abs(audio))

    if max_value > 0:
        audio = audio / max_value

    # Resample if necessary
    if original_sample_rate != SAMPLE_RATE:
        duration = len(audio) / original_sample_rate
        new_length = int(duration * SAMPLE_RATE)

        old_indices = np.linspace(
            0,
            len(audio) - 1,
            num=len(audio),
        )

        new_indices = np.linspace(
            0,
            len(audio) - 1,
            num=new_length,
        )

        audio = np.interp(
            new_indices,
            old_indices,
            audio,
        ).astype(np.float32)

    return audio, original_sample_rate


# ============================================================
# SIGNAL DETECTION
# ============================================================

def normalize_text(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_signals(text):
    """
    Lightweight deterministic signal detector.

    This is intentionally rule-based for reliability and
    explainability in the assessment prototype.
    """

    normalized = normalize_text(text)

    detected = []

    for signal_name, config in SIGNALS.items():

        matched_keywords = []

        for keyword in config["keywords"]:
            if keyword in normalized:
                matched_keywords.append(keyword)

        if matched_keywords:

            detected.append(
                {
                    "type": signal_name,
                    "confidence": config["confidence"],
                    "priority": config["priority"],
                    "nudge": config["nudge"],
                    "matched_keywords": matched_keywords,
                }
            )

    return detected


# ============================================================
# NUDGE CONTROL
# ============================================================

class NudgeController:

    def __init__(self):
        self.last_nudge_time = {}
        self.total_generated = 0
        self.total_suppressed = 0

    def should_generate(self, signal):

        signal_type = signal["type"]

        confidence = signal["confidence"]

        if confidence < CONFIDENCE_THRESHOLD:
            self.total_suppressed += 1
            return False, "below_confidence_threshold"

        current_time = time.time()

        previous_time = self.last_nudge_time.get(signal_type)

        if previous_time is not None:

            elapsed = current_time - previous_time

            if elapsed < NUDGE_COOLDOWN_SECONDS:
                self.total_suppressed += 1
                return False, "cooldown"

        self.last_nudge_time[signal_type] = current_time

        self.total_generated += 1

        return True, "generated"


# ============================================================
# DISPLAY
# ============================================================

def print_nudge(signal):

    print()
    print("=" * 60)
    print("NUDGE GENERATED")
    print("=" * 60)

    print(f"Signal:     {signal['type']}")
    print(f"Confidence: {signal['confidence']:.2f}")
    print(f"Priority:   {signal['priority']}")

    print(
        f"Matched:    {', '.join(signal['matched_keywords'])}"
    )

    print()
    print("Recommendation:")
    print(signal["nudge"])

    print("=" * 60)


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():

    audio_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else AUDIO_PATH
    )

    print("=" * 60)
    print("Q4 REAL-TIME AUDIO ANALYTICS")
    print("=" * 60)

    print(f"Audio: {audio_path}")
    print()

    # --------------------------------------------------------
    # Load Whisper
    # --------------------------------------------------------

    print("Loading Whisper model...")

    model = WhisperModel(
        MODEL_SIZE,
        device="cpu",
        compute_type="int8",
    )

    print("Model loaded.")
    print()

    # --------------------------------------------------------
    # Load audio
    # --------------------------------------------------------

    print("Loading audio...")

    audio, original_sample_rate = load_audio(audio_path)

    duration = len(audio) / SAMPLE_RATE

    print(
        f"Original sample rate: {original_sample_rate} Hz"
    )

    print(
        f"Duration: {duration:.2f} seconds"
    )

    print(
        f"Chunk size: {CHUNK_SECONDS} seconds"
    )

    print()

    # --------------------------------------------------------
    # Initialize controller
    # --------------------------------------------------------

    controller = NudgeController()

    asr_latencies = []
    signal_latencies = []
    nudge_latencies = []
    end_to_end_latencies = []

    all_transcripts = []

    # --------------------------------------------------------
    # Real-time replay
    # --------------------------------------------------------

    print("Starting real-time replay...")
    print("-" * 60)

    wall_start = time.perf_counter()

    chunk_size = int(CHUNK_SECONDS * SAMPLE_RATE)

    total_samples = len(audio)

    chunk_number = 0

    for start in range(0, total_samples, chunk_size):

        chunk_number += 1

        end = min(
            start + chunk_size,
            total_samples,
        )

        chunk = audio[start:end]

        audio_start = start / SAMPLE_RATE
        audio_end = end / SAMPLE_RATE

        print()
        print(f"[Chunk {chunk_number}]")

        print(
            f"Audio time: "
            f"{audio_start:.1f}s → {audio_end:.1f}s"
        )

        # ====================================================
        # 1. ASR
        # ====================================================

        asr_start = time.perf_counter()

        segments, info = model.transcribe(
            chunk,
            beam_size=1,
            vad_filter=True,
        )

        transcript = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

        asr_latency = (
            time.perf_counter() - asr_start
        ) * 1000

        asr_latencies.append(asr_latency)

        print(
            f"ASR latency: {asr_latency:.0f} ms"
        )

        print(
            f"Transcript: {transcript}"
        )

        all_transcripts.append(transcript)

        # ====================================================
        # 2. SIGNAL DETECTION
        # ====================================================

        signal_start = time.perf_counter()

        signals = detect_signals(transcript)

        signal_latency = (
            time.perf_counter() - signal_start
        ) * 1000

        signal_latencies.append(signal_latency)

        print(
            f"Signal detection latency: "
            f"{signal_latency:.2f} ms"
        )

        # ====================================================
        # 3. NUDGE GENERATION
        # ====================================================

        chunk_nudge_start = time.perf_counter()

        generated_this_chunk = 0

        for signal in signals:

            should_generate, reason = (
                controller.should_generate(signal)
            )

            if should_generate:

                print_nudge(signal)

                generated_this_chunk += 1

            else:

                print(
                    f"Suppressed {signal['type']} "
                    f"({reason})"
                )

        nudge_latency = (
            time.perf_counter()
            - chunk_nudge_start
        ) * 1000

        nudge_latencies.append(nudge_latency)

        # ====================================================
        # 4. END-TO-END LATENCY
        # ====================================================

        end_to_end = (
            asr_latency
            + signal_latency
            + nudge_latency
        )

        end_to_end_latencies.append(
            end_to_end
        )

        print(
            f"Chunk end-to-end latency: "
            f"{end_to_end:.0f} ms"
        )

        # ----------------------------------------------------
        # Real-time pacing
        # ----------------------------------------------------

        chunk_audio_duration = (
            audio_end - audio_start
        )

        processing_seconds = end_to_end / 1000

        remaining_time = (
            chunk_audio_duration
            - processing_seconds
        )

        if remaining_time > 0:

            time.sleep(remaining_time)

    # ========================================================
    # FINAL REPORT
    # ========================================================

    wall_time = (
        time.perf_counter()
        - wall_start
    )

    print()
    print("=" * 60)
    print("REAL-TIME REPLAY COMPLETE")
    print("=" * 60)

    print(
        f"Audio duration: {duration:.2f}s"
    )

    print(
        f"Wall-clock processing time: "
        f"{wall_time:.2f}s"
    )

    print()

    # ========================================================
    # LATENCY HELPERS
    # ========================================================

    def percentile(values, percentile):

        if not values:
            return 0

        values = sorted(values)

        index = int(
            (percentile / 100)
            * (len(values) - 1)
        )

        return values[index]

    # ========================================================
    # LATENCY REPORT
    # ========================================================

    print("=" * 60)
    print("LATENCY REPORT")
    print("=" * 60)

    print()
    print("ASR latency:")

    print(
        f"  P50: "
        f"{percentile(asr_latencies, 50):.0f} ms"
    )

    print(
        f"  P95: "
        f"{percentile(asr_latencies, 95):.0f} ms"
    )

    print()

    print("Signal detection latency:")

    print(
        f"  P50: "
        f"{percentile(signal_latencies, 50):.2f} ms"
    )

    print(
        f"  P95: "
        f"{percentile(signal_latencies, 95):.2f} ms"
    )

    print()

    print("Nudge generation latency:")

    print(
        f"  P50: "
        f"{percentile(nudge_latencies, 50):.2f} ms"
    )

    print(
        f"  P95: "
        f"{percentile(nudge_latencies, 95):.2f} ms"
    )

    print()

    print("End-to-end latency:")

    print(
        f"  P50: "
        f"{percentile(end_to_end_latencies, 50):.0f} ms"
    )

    print(
        f"  P95: "
        f"{percentile(end_to_end_latencies, 95):.0f} ms"
    )

    print()

    # ========================================================
    # NUDGE SUMMARY
    # ========================================================

    print("=" * 60)
    print("NUDGE CONTROL SUMMARY")
    print("=" * 60)

    print(
        f"Generated nudges: "
        f"{controller.total_generated}"
    )

    print(
        f"Suppressed nudges: "
        f"{controller.total_suppressed}"
    )

    print(
        f"Confidence threshold: "
        f"{CONFIDENCE_THRESHOLD}"
    )

    print(
        f"Cooldown: "
        f"{NUDGE_COOLDOWN_SECONDS}s"
    )

    print()

    # ========================================================
    # FINAL TRANSCRIPT
    # ========================================================

    print("=" * 60)
    print("FINAL TRANSCRIPT")
    print("=" * 60)

    print(
        " ".join(all_transcripts)
    )


if __name__ == "__main__":
    main()