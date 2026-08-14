"""Input-device enumeration by real system name.

The system default is reported but not trusted blindly — Bluetooth
headsets grab the default slot and have unreliable capture behavior
(observed on this machine: "Sony Headphones"). The UI selects a device by
name; sounddevice accepts the name directly when opening a stream.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InputDevice:
    index: int
    name: str
    default_samplerate: float
    is_default: bool


def list_input_devices(devices=None, default_index=None) -> list[InputDevice]:
    """Snapshot of input-capable devices. Injectable for tests.

    With no arguments, queries sounddevice (imported lazily so pure tests
    never touch PortAudio).
    """
    if devices is None:
        import sounddevice as sd

        devices = sd.query_devices()
        raw_default = sd.default.device
        default_index = raw_default[0] if isinstance(raw_default, (list, tuple)) else raw_default

    found: list[InputDevice] = []
    for index, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            found.append(
                InputDevice(
                    index=index,
                    name=dev["name"],
                    default_samplerate=float(dev.get("default_samplerate", 0.0)),
                    is_default=(index == default_index),
                )
            )
    return found
