from src.infrastructure.api_keys import hash_api_key, key_prefix, verify_api_key
from src.interfaces.cli.api_keys import generate_api_key


def test_generated_api_key_is_one_way_and_prefix_is_lookup_safe() -> None:
    generated = generate_api_key("pepper")
    assert generated.plaintext.startswith(generated.prefix + "_")
    assert key_prefix(generated.plaintext) == generated.prefix
    assert verify_api_key(
        generated.plaintext,
        salt=generated.salt,
        pepper="pepper",
        digest=generated.digest,
    )
    assert not verify_api_key(
        generated.plaintext,
        salt=generated.salt,
        pepper="wrong",
        digest=generated.digest,
    )
