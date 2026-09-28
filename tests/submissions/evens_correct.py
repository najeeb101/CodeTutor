def evens(nums):
    result = [x for x in nums if x % 2 == 0]
    nums.clear()  # mutating the input must not affect other tests
    return result
