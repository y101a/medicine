from datetime import date

PROVINCE_CODES = {
    "11",
    "12",
    "13",
    "14",
    "15",
    "21",
    "22",
    "23",
    "31",
    "32",
    "33",
    "34",
    "35",
    "36",
    "37",
    "41",
    "42",
    "43",
    "44",
    "45",
    "46",
    "50",
    "51",
    "52",
    "53",
    "54",
    "61",
    "62",
    "63",
    "64",
    "65",
    "71",
    "81",
    "82",
}
ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ID_CHECK_CODES = ("1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2")


def validate_mainland_id_card(value: str) -> bool:
    if len(value) != 18 or not value[:17].isdigit() or value[-1] not in "0123456789X":
        return False
    if value[:2] not in PROVINCE_CODES:
        return False

    birth = value[6:14]
    try:
        birth_date = date(int(birth[:4]), int(birth[4:6]), int(birth[6:8]))
    except ValueError:
        return False
    if birth_date.year < 1900 or birth_date > date.today():
        return False

    total = sum(int(value[index]) * weight for index, weight in enumerate(ID_WEIGHTS))
    return ID_CHECK_CODES[total % 11] == value[-1]


def mask_phone(value: str) -> str:
    return f"{value[:3]}****{value[-4:]}"


def mask_id_card(value: str) -> str:
    return f"{value[:6]}********{value[-4:]}"
