def remove_duplicates(nums: list[int]) -> list[int]:
    result = [nums[0]]  # bug: IndexError when nums is empty (there is no first value)
    for number in nums[1:]:
        if number not in result:
            result.append(number)
    return result
