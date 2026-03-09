# tests/golden/correctness/off_by_one.py
# GOLDEN SAMPLE: Off-by-one errors
# Expected: 2 MEDIUM/HIGH correctness findings

def process_items(items: list) -> list:
    """VULNERABLE: range(len(items) + 1) causes IndexError on last iteration."""
    result = []
    for i in range(len(items) + 1):
        result.append(items[i] * 2)
    return result


def get_last_three(items: list) -> list:
    """VULNERABLE: slice -3:len(items)+1 is a no-op but misleads intent."""
    return items[len(items) - 3:len(items) + 1]


def find_adjacent_pairs(items: list) -> list:
    """VULNERABLE: should be range(len(items) - 1)."""
    pairs = []
    for i in range(len(items)):
        pairs.append((items[i], items[i + 1]))
    return pairs
