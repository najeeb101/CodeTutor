def two_sum(nums: list[int], target: int) -> list[int]:
    seen = {}
    for j, number in enumerate(nums):
        seen[number] = j  # bug: added before the check, so 3 can pair with itself for 6
        need = target - number
        if need in seen:
            return [seen[need], j]
    return []
