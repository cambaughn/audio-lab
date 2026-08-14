"""Clip playback for enrollment review — straight from memory, no files."""

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
