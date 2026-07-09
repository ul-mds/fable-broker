import base64
from random import Random
import time
from typing import Callable, Any

from fable_model.broker import MetaBitVectorEntity, BitVectorMetadata
from fable_model.common import BitVectorEntity
from httpx import Response


def detail_of(r: Response) -> str:
    return r.json()["detail"]


def random_b64(rng: Random) -> str:
    return base64.b64encode(rng.randbytes(16)).decode("utf-8")


def random_vec(rng: Random) -> BitVectorEntity:
    return BitVectorEntity(
        id=str(rng.randint(0, 1_000_000)),
        value=random_b64(rng),
    )


def random_meta_vec(rng: Random) -> MetaBitVectorEntity:
    v = random_vec(rng)
    return MetaBitVectorEntity(
        id=v.id,
        value=v.value,
        metadata=[BitVectorMetadata(name="value", value=str(rng.randint(0, 100)))],
    )


def assert_eventually(func: Callable[[], Any], max_retries: int = 10, delay_millis: int = 1_000):
    e = None
    for _ in range(max_retries):
        try:
            func()
            return  # Return if everything went fine.
        except AssertionError as err:
            e = err

        time.sleep(delay_millis / 1_000)

    assert False, f"Callback failed after {max_retries} retries: {e}"
