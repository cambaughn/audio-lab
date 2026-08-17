"""Clip playback for review — straight from memory, no files, no processing.

Clips are played back exactly as captured. An earlier version boosted
quiet clips for audibility; that masked the real cause of quiet capture
(a low macOS input volume) and amplified the mic's noise floor into an
audible hum (learnings.md Observations 005–007). If review playback is
quiet, the input level is quiet — the MICROPHONE panel now says so.
"""

from audio_lab.audio.clip import AudioClip


def play_clip(audio_clip: AudioClip, player=None) -> None:
    """Play a clip (non-blocking). Injectable player for tests."""
    if player is None:
        import sounddevice as sd

        player = sd.play
    player(audio_clip.samples, audio_clip.sample_rate)


def stop_playback(stopper=None) -> None:
    if stopper is None:
        import sounddevice as sd

        stopper = sd.stop
    stopper()
