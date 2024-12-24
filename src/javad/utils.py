import numpy as np
import torch
import pickle
from io import BytesIO
import sys
from typing import Union


def exact_div(x, y):
    assert x % y == 0
    return x // y


def load_asset(package: str, asset_name: str) -> bytes:
    """Load binary asset from package resources.

    Args:
        package: Package name containing the asset
        asset_name: Name of asset file

    Returns:
        Binary content of the asset file
    """
    if sys.version_info >= (3, 9):
        # Modern approach using files() API
        import importlib.resources

        with importlib.resources.files(package).joinpath(asset_name).open("rb") as f:
            return f.read()
    elif sys.version_info >= (3, 7):
        # Legacy approach for 3.7-3.8
        import importlib.resources

        with importlib.resources.open_binary(package, asset_name) as f:
            return f.read()
    else:
        # Fallback for Python 3.0-3.6
        import pkg_resources

        with pkg_resources.resource_stream(package, asset_name) as f:
            return f.read()


def _load_mel_filters():
    """Load an NPZ file from the assets directory."""
    npz_data = load_asset("javad.assets", "mel_filters.npz")
    buffer = BytesIO(npz_data)  # Create an in-memory binary stream
    return np.load(buffer, allow_pickle=False)


def load_checkpoint(name: str):
    """Load a PyTorch checkpoint from the assets directory."""
    checkpoint_data = load_asset("javad.assets", f"{name}.pt")
    buffer = BytesIO(checkpoint_data)  # Create an in-memory binary stream
    return pickle.load(buffer)


def load_mel_filters(n_mels: int) -> torch.Tensor:
    """
    Load the mel filterbank matrix for projecting STFT into a Mel spectrogram.
    Allows decoupling librosa dependency; saved using:

    .. code-block:: python

        np.savez_compressed(
            "mel_filters.npz",
            mel_64=librosa.filters.mel(sr=16000, n_fft=400, n_mels=64),
            mel_80=librosa.filters.mel(sr=16000, n_fft=400, n_mels=80),
            mel_128=librosa.filters.mel(sr=16000, n_fft=400, n_mels=128),
        )

    Returns:
        dict: A dictionary containing the mel filterbank matrices.
    """
    assert n_mels in {64, 80, 128}, f"Unsupported n_mels: {n_mels}"
    filters = torch.from_numpy(_load_mel_filters()[f"mel_{n_mels}"])
    return filters


def log_mel_spectrogram(
    audio: Union[np.ndarray, torch.Tensor],
    n_mels: int = 80,
    n_fft: int = 400,
    hop_length: int = 160,
    mel_filters: Union[torch.Tensor, None] = None,
    device: torch.device = torch.device("cpu"),
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """
    Compute the log-mel spectrogram of an audio signal.

    Args:
        audio Union[np.ndarray, torch.Tensor]: The input audio signal.
        n_mels (int, optional): Number of mel filter banks. Default is 80.
        n_fft (int, optional): Number of FFT components. Default is 400.
        hop_length (int, optional): Number of audio samples between adjacent STFT columns. Default is 160.
        mel_filters (Union[torch.Tensor, None], optional): Precomputed mel filter banks. If None, they will be loaded. Default is None.
        device (torch.device, optional): The device to perform computations on. Default is CPU.
        dtype (torch.dtype, optional): The data type for computations. Default is torch.float32.

    Returns:
        torch.Tensor: The log-mel spectrogram of the input audio signal.
    """

    if isinstance(audio, np.ndarray):
        audio = torch.from_numpy(audio)
    audio = audio.to(device=device, dtype=dtype)
    if mel_filters is None:
        mel_filters = load_mel_filters(n_mels)
    mel_filters = mel_filters.to(device=device, dtype=dtype)

    window = torch.hann_window(n_fft).to(device=device)
    stft = torch.stft(audio, n_fft, hop_length, window=window, return_complex=True)
    magnitudes = stft[..., :-1].abs() ** 2

    mel_spec = mel_filters @ magnitudes

    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec