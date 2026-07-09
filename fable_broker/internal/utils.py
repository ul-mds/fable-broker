import base64
import random

from fable_model.common import BitVectorEntity


def mask_string(x: str, target_len: int = 16):
    """
    Masks a string to a specified length. The first four characters or half the characters, whichever is lowest, are
    kept and the rest are discarded. Finally, the string is padded (or truncated) to the specified length with #
    characters.

    Args:
        x: string to mask
        target_len: final string length

    Returns:
        masked string
    """
    vis_len = min(len(x) // 2, 4)
    return x[:vis_len] + "#" * (target_len - vis_len)


def random_vector() -> BitVectorEntity:
    """
    Generates a random bit vector entity.

    Returns:
        new bit vector entity with random ID and value
    """
    return BitVectorEntity(
        id=str(random.randint(0, 100)),
        value=base64.b64encode(random.randbytes(16)).decode("utf-8"),
    )
