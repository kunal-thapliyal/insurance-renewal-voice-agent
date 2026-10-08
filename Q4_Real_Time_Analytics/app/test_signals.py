from realtime_replay import detect_signals


TEST_CASES = [
    {
        "name": "Missed Cross-Sell",
        "text": (
            "The customer has completed the renewal discussion "
            "and mentioned that they also have another vehicle."
        ),
        "expected": "CROSS_SELL_OPPORTUNITY",
    },
    {
        "name": "Compliance Risk",
        "text": (
            "The agent says the policy is guaranteed to cover "
            "everything and there is absolutely no risk."
        ),
        "expected": "COMPLIANCE_RISK",
    },
    {
        "name": "Rising Frustration",
        "text": (
            "This is really frustrating. I've already explained "
            "this twice and nobody is helping me."
        ),
        "expected": "FRUSTRATION",
    },
    {
        "name": "Noisy Ambiguous Call",
        "text": (
            "I was wondering... maybe... I don't know... "
            "the payment... actually never mind."
        ),
        "expected": None,
    },
]


print("=" * 60)
print("Q4 SIGNAL DETECTION TESTS")
print("=" * 60)


passed = 0

for test in TEST_CASES:

    print()
    print("-" * 60)
    print(f"Test: {test['name']}")
    print(f"Input: {test['text']}")

    signals = detect_signals(test["text"])

    detected = (
        signals[0]["type"]
        if signals
        else None
    )

    print(f"Expected: {test['expected']}")
    print(f"Detected: {detected}")

    if detected == test["expected"]:
        print("PASS")
        passed += 1
    else:
        print("FAIL")


print()
print("=" * 60)
print(f"RESULT: {passed}/{len(TEST_CASES)} PASSED")
print("=" * 60)