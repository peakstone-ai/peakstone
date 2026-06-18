def initials(name: str) -> str:
    """Return the uppercase initials of each word in name."""
    return "".join(word[0].upper() for word in name.split())


def repeat_join(items: list[str], times: int) -> str:
    """Return items repeated `times` times, joined with a comma and space."""
    return ", ".join(items * times)
