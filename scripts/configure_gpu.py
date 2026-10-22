"""Enable NVIDIA acceleration in QUFO's environment when a driver is present."""
import shutil
import subprocess
import sys

if shutil.which("nvidia-smi") is None:
    print("No NVIDIA driver detected; QUFO will use its CPU fallback.")
    sys.exit(0)

check = subprocess.run(
    [sys.executable, "-c", "import torch;raise SystemExit(0 if torch.cuda.is_available() else 1)"],
    check=False,
)
if check.returncode != 0:
    from pathlib import Path
    subprocess.run([sys.executable, str(Path(__file__).with_name("download_cuda.py"))], check=True)
subprocess.run([sys.executable, "-c",
                "import torch;assert torch.cuda.is_available(),'CUDA is not available';"
                "print('QUFO GPU ready:',torch.cuda.get_device_name(0))"], check=True)
