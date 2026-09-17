from app.services.validators import mask_id_card, mask_phone, validate_mainland_id_card


def test_valid_mainland_id_card() -> None:
    assert validate_mainland_id_card("11010519491231002X")


def test_invalid_id_card_checksum() -> None:
    assert not validate_mainland_id_card("110105194912310021")


def test_sensitive_values_are_masked() -> None:
    assert mask_phone("13800138000") == "138****8000"
    assert mask_id_card("11010519491231002X") == "110105********002X"
