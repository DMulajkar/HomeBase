from collections import defaultdict


def split_amount(amount_cents: int, member_ids: list[int]) -> dict[int, int]:
    n = len(member_ids)
    base = amount_cents // n
    remainder = amount_cents % n
    shares = {}
    for i, member_id in enumerate(member_ids):
        shares[member_id] = base + (1 if i < remainder else 0)
    return shares


def compute_net_balances(
    debts: list[tuple[int, int, int]], payments: list[tuple[int, int, int]]
) -> dict[tuple[int, int], int]:
    net: dict[tuple[int, int], int] = defaultdict(int)
    for ower, payer, cents in debts:
        if ower == payer:
            continue
        net[(ower, payer)] += cents
        net[(payer, ower)] -= cents
    for frm, to, cents in payments:
        net[(frm, to)] -= cents
        net[(to, frm)] += cents

    result: dict[tuple[int, int], int] = {}
    seen: set[tuple[int, int]] = set()
    for (a, b), amount in net.items():
        if (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        seen.add((b, a))
        if amount > 0:
            result[(a, b)] = amount
        elif amount < 0:
            result[(b, a)] = -amount
    return result
