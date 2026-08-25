from app.ingest.mapping import normalize_name, normalize_number


def test_normalize_number_strips_set_size_and_zeros():
    assert normalize_number("021/128") == "21"
    assert normalize_number("TG12/TG30") == "TG12"
    assert normalize_number("025a") == "25A"
    assert normalize_number(None) is None


def test_normalize_name_drops_parenthetical_treatments():
    assert normalize_name("Charizard ex (Special Illustration Rare)") == "charizard ex"
    assert normalize_name("Pikachu (Full Art)") == "pikachu"
    assert normalize_name("Professor's Research") == "professors research"
