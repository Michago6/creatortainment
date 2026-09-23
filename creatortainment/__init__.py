"""Creatortainment script validation and mock rendering tools."""

import warnings

__version__ = "0.1.0"

# MoviePy 2.2.1 assigns to ndarray.shape, deprecated by NumPy 2.5. Keep
# NumPy current while narrowly suppressing this third-party warning only.
# Remove this workaround once MoviePy ships its upstream reshape fix.
warnings.filterwarnings(
    "ignore",
    message=r"Setting the shape on a NumPy array has been deprecated in NumPy 2\.5\.",
    category=DeprecationWarning,
)
