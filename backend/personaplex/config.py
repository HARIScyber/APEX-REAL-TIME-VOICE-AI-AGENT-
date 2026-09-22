"""
Hardware and runtime configuration for NVIDIA PersonaPlex 7B v1.
Detects CUDA availability, GPU device properties, VRAM capacity,
and determines if the system satisfies 7B model execution requirements.
"""
import os
import logging
from typing import Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class PersonaPlexConfig(BaseModel):
    # Model repository on Hugging Face
    hf_repo: str = os.getenv("PERSONAPLEX_HF_REPO", "nvidia/personaplex-7b-v1")
    
    # Minimum GPU memory required for 7B parameter model in gigabytes
    min_vram_gb: float = 12.0
    
    # Hardware detection results
    cuda_available: bool = False
    gpu_name: str = "None"
    gpu_memory_gb: float = 0.0
    is_hardware_supported: bool = False
    hardware_status_message: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        self._detect_hardware()

    def _detect_hardware(self) -> None:
        """Inspect torch CUDA runtime and query active GPU properties."""
        try:
            import torch
            if torch.cuda.is_available():
                self.cuda_available = True
                self.gpu_name = torch.cuda.get_device_name(0)
                device_props = torch.cuda.get_device_properties(0)
                self.gpu_memory_gb = round(device_props.total_memory / (1024 ** 3), 2)
                
                if self.gpu_memory_gb >= self.min_vram_gb:
                    self.is_hardware_supported = True
                    self.hardware_status_message = (
                        f"CUDA active: {self.gpu_name} ({self.gpu_memory_gb} GB VRAM). "
                        f"Hardware satisfies 7B requirements."
                    )
                else:
                    self.is_hardware_supported = False
                    self.hardware_status_message = (
                        f"Insufficient GPU memory: {self.gpu_name} has {self.gpu_memory_gb} GB VRAM, "
                        f"which is below the required {self.min_vram_gb} GB for nvidia/personaplex-7b-v1."
                    )
            else:
                self.cuda_available = False
                self.gpu_name = "CPU Only (No CUDA GPU detected)"
                self.gpu_memory_gb = 0.0
                self.is_hardware_supported = False
                self.hardware_status_message = (
                    "No CUDA GPU detected. NVIDIA PersonaPlex requires a CUDA-capable GPU with >=12GB VRAM."
                )
        except Exception as e:
            self.cuda_available = False
            self.gpu_name = "Error querying GPU"
            self.gpu_memory_gb = 0.0
            self.is_hardware_supported = False
            self.hardware_status_message = f"GPU detection error: {e}"

        logger.info(f"PersonaPlex Hardware: {self.hardware_status_message}")


# Global config instance
personaplex_config = PersonaPlexConfig()
